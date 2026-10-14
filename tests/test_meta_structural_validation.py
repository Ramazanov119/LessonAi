import ast
import copy
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from docx import Document
from config.colleges import get_college_config
from services.ai import create_lesson, AIServiceError
from services.lesson_validation import normalize_meta_lesson, LessonValidationError
from services.lesson_plan_service import save_generated_lesson_plan
from services.meta_diagnostics import record_meta_failure, anonymized_snapshot
from test_meta_task_links import metadata

FIXTURES = Path(__file__).with_name('fixtures')


def ios(code='ru'):
    return json.loads((FIXTURES / f'meta_ios_{code}.json').read_text())


class MetaStructuralValidationTest(unittest.TestCase):
    def test_reported_descriptor_without_shared_words_passes_ru_and_kk(self):
        for code, language in (('ru', 'Русский'), ('kk', 'Қазақша')):
            with self.subTest(language=language):
                plan = ios(code)
                result = normalize_meta_lesson(plan, language=language, lesson_type='Новый урок', lesson_date=date(2026, 10, 13))
                expected = 'Аргументирует выводы с примерами' if code == 'ru' else 'Қорытындыны мысалдармен дәлелдейді'
                self.assertEqual(result['assessment_items'][0]['descriptors'][0], expected)
                self.assertEqual(result['assessment_items'][0]['descriptor_details'][0]['task_id'], 'task_1')
                self.assertEqual(sum(i['points'] for i in result['assessment_items']), 100)
                self.assertEqual(sum(s['duration_minutes'] for s in result['lesson_stages']), 70)
                self.assertEqual(result, normalize_meta_lesson(result, language=language, lesson_date=date(2026, 10, 13)))

    def test_legacy_descriptor_sentence_inherits_task_without_new_action_text(self):
        plan = ios()
        plan['assessment_items'][0]['descriptors'] = ['Аргументирует выводы с примерами', 'Демонстрирует выполненную работу']
        result = normalize_meta_lesson(plan)
        self.assertEqual(result['assessment_items'][0]['descriptor_points'], [10, 10])
        self.assertEqual(result['assessment_items'][0]['descriptor_details'][0]['action'], 'Аргументирует выводы с примерами')

    def test_unrelated_vocabulary_is_not_a_membership_test(self):
        plan = ios()
        # Observable general result, not a repetition of iOS/task/stage wording.
        value = plan['assessment_items'][0]['descriptors'][0]
        value.update(text='Подкрепляет позицию двумя подтверждениями', action='Подкрепляет позицию', result='Два подтверждения')
        result = normalize_meta_lesson(plan)
        self.assertEqual(result['assessment_items'][0]['descriptors'][0], value['text'])

    def test_bad_task_stage_duplicate_and_descriptor_references_are_rejected(self):
        for kind, expected in (('unknown', 'unknown_task_id'), ('wrong_stage', 'wrong_task_stage'),
                               ('duplicate', 'duplicate_assessment'), ('descriptor', 'assessment_reference_mismatch'),
                               ('criterion', 'assessment_reference_mismatch')):
            with self.subTest(kind=kind):
                plan = ios()
                item = plan['assessment_items'][0]
                if kind == 'unknown': item['task_id'] = 'missing'
                elif kind == 'wrong_stage': item['stage_key'] = 'practice'
                elif kind == 'duplicate': plan['assessment_items'].append(copy.deepcopy(item))
                elif kind == 'descriptor': item['descriptors'][0]['task_id'] = 'task_2'
                else: item['assessment_criterion']['task_id'] = 'task_2'
                with self.assertRaises(LessonValidationError) as error:
                    normalize_meta_lesson(plan)
                self.assertEqual(error.exception.code, expected)
                self.assertIsNotNone(error.exception.task_id)

    def test_missing_observable_action_and_required_result_are_rejected(self):
        for field, value, expected in (('action', '', 'missing_observable_action'),
                                       ('result', None, 'missing_descriptor_result'),
                                       ('requires_result', 'yes', 'invalid_descriptor_result_flag')):
            with self.subTest(field=field):
                plan = ios()
                plan['assessment_items'][0]['descriptors'][0][field] = value
                with self.assertRaises(LessonValidationError) as error:
                    normalize_meta_lesson(plan)
                self.assertEqual(error.exception.code, expected)
                self.assertEqual(error.exception.task_id, 'task_1')

    def test_raw_weights_are_scaled_but_canonical_scores_are_not_repaired(self):
        plan = ios()
        for item in plan['assessment_items']:
            item['points'] = 10
            for descriptor in item['descriptors']: descriptor['points'] = 5
        result = normalize_meta_lesson(plan)
        self.assertEqual([item['points'] for item in result['assessment_items']], [20] * 5)
        plan = result
        plan['assessment_items'][0]['descriptor_points'][0] = 9
        with self.assertRaises(LessonValidationError) as error:
            normalize_meta_lesson(plan)
        self.assertEqual(error.exception.code, 'descriptor_points_total')

    def test_safe_missing_id_in_unique_stage_is_recovered_without_word_matching(self):
        plan = ios()
        plan['assessment_items'][0].pop('task_id')
        plan['assessment_items'][0]['task_name'] = 'Перефразированное название'
        result = normalize_meta_lesson(plan)
        self.assertEqual(result['assessment_items'][0]['task_id'], 'task_1')
        self.assertEqual(result['assessment_items'][0]['task_name'], plan['lesson_stages'][1]['tasks'][0]['name'])

    def test_old_text_only_plan_does_not_invent_tasks(self):
        plan = ios()
        for stage in plan['lesson_stages']: stage.pop('tasks', None)
        for item in plan['assessment_items']: item.pop('task_id', None)
        with self.assertRaises(LessonValidationError) as error:
            normalize_meta_lesson(plan)
        self.assertEqual(error.exception.code, 'missing_task_reference')

    @patch('services.ai.openai_generate')
    def test_ios_full_flow_one_provider_call_docx_before_atomic_save(self, provider):
        provider.return_value = json.dumps(ios())
        generated = create_lesson('Мобильная разработка', 'Операционная система iOS', 'Русский', 'IT', 'Chair',
                                  'Новый урок', 70, None, college='META', lesson_date=date(2026, 10, 13))
        provider.assert_called_once()
        prompt = provider.call_args.args[0]
        self.assertNotIn('одинаковую терминологию', prompt)
        self.assertIn('action (наблюдаемое действие)', prompt)
        service = Mock()
        service.save_lesson_plan.return_value = {'lesson_id': 'fake', 'daily_count': 1}
        document, _ = save_generated_lesson_plan(service, generated, metadata(), get_college_config('META')['template'])
        self.assertIn('Аргументирует выводы с примерами', Document(document).tables[2].rows[1].cells[3].text)
        service.save_lesson_plan.assert_called_once()

    def test_failures_do_not_consume_quota_and_retry_does_not_call_non_atomic_paths(self):
        service = Mock()
        bad = ios()
        bad['assessment_items'][0]['task_id'] = 'missing'
        for _ in range(2):
            with self.assertRaises(LessonValidationError):
                save_generated_lesson_plan(service, bad, metadata(), get_college_config('META')['template'])
        service.save_lesson_plan.assert_not_called()
        service.create_lesson.assert_not_called()
        service.upsert_material.assert_not_called()
        service.save_lesson_plan.return_value = {'lesson_id': 'fake', 'daily_count': 1}
        save_generated_lesson_plan(service, ios(), metadata(), get_college_config('META')['template'])
        service.save_lesson_plan.assert_called_once()


class MetaDiagnosticsTest(unittest.TestCase):
    def test_disabled_by_default_and_cannot_enable_in_production(self):
        error = LessonValidationError('secret message', code='unknown_task_id', task_id='secret-id')
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(record_meta_failure(ios(), error, 'normalization'))
        with patch.dict(os.environ, {'LESSONAI_ENV': 'production', 'LESSONAI_META_DIAGNOSTICS': '1'}, clear=True):
            self.assertIsNone(record_meta_failure(ios(), error, 'normalization'))

    def test_capture_has_no_raw_text_keys_names_or_personal_ids(self):
        plan = ios()
        secret = 'sk-never-log-api-key'
        identity = 'Иванов Иван student@example.com +77001112233'
        plan.update(teacher=identity, students=[identity], api_key=secret)
        plan['lesson_stages'][1]['tasks'][0]['name'] = identity
        plan['lesson_stages'][1]['content'] += secret
        plan['assessment_items'][0]['descriptors'][0]['text'] += identity + secret
        plan['assessment_items'][0]['task_id'] = identity
        error = LessonValidationError(identity + secret, code='unknown_task_id', task_id=identity)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'LESSONAI_ENV': 'development', 'LESSONAI_META_DIAGNOSTICS': '1', 'LESSONAI_META_DIAGNOSTIC_DIR': directory,
        }, clear=True):
            path = record_meta_failure(plan, error, 'normalization')
            raw = path.read_text()
            self.assertNotIn(secret, raw)
            self.assertNotIn(identity, raw)
            self.assertNotIn('teacher', raw)
            snapshot = json.loads(raw)
            self.assertEqual(snapshot['error']['code'], 'unknown_task_id')
            self.assertEqual(snapshot['phase'], 'normalization')
            self.assertIsNone(record_meta_failure(plan, error, 'normalization'))
            self.assertEqual(len(list(Path(directory).glob('*.json'))), 1)
            with self.assertRaises(LessonValidationError) as replay:
                normalize_meta_lesson(snapshot['lesson'])
            self.assertEqual(replay.exception.code, 'unknown_task_id')

    def test_diagnostic_io_failure_never_masks_validation(self):
        with patch('services.meta_diagnostics.meta_diagnostic_directory', return_value=Path('/unused')), patch('pathlib.Path.mkdir', side_effect=OSError('blocked')):
            self.assertIsNone(record_meta_failure(ios(), LessonValidationError('bad'), 'normalization'))

    def test_saved_snapshot_fixture_reproduces_reference_failure(self):
        snapshot = json.loads((FIXTURES / 'meta_rejected_unknown_task.json').read_text())
        with self.assertRaises(LessonValidationError) as error:
            normalize_meta_lesson(snapshot['lesson'])
        self.assertEqual(error.exception.code, snapshot['error']['code'])

    def test_normalized_descriptor_details_remain_replayable_without_private_text(self):
        from services.meta_diagnostics import anonymized_snapshot
        plan = normalize_meta_lesson(ios())
        plan['assessment_items'][0]['descriptor_details'][0]['task_id'] = 'private@example.com'
        error = LessonValidationError('private error', code='assessment_reference_mismatch', task_id=plan['assessment_items'][0]['task_id'])
        snapshot = anonymized_snapshot(plan, error, 'docx')
        self.assertNotIn('private@example.com', json.dumps(snapshot))
        with self.assertRaises(LessonValidationError) as replay:
            normalize_meta_lesson(snapshot['lesson'])
        self.assertEqual(replay.exception.code, 'assessment_reference_mismatch')

    def test_ui_failure_logging_does_not_dump_exception_text_or_metadata(self):
        root = Path(__file__).resolve().parents[1]
        function = next(n for n in ast.parse((root / 'app.py').read_text()).body if isinstance(n, ast.FunctionDef) and n.name == '_log_create_failure')
        logger = Mock()
        namespace = {'logger': logger}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(root / 'app.py'), 'exec'), namespace)
        namespace['_log_create_failure']('lesson_plan', 'AI generation', 'student@example.com', 'personal topic',
                                        LessonValidationError('API sk-secret', code='unknown_task_id', task_id='teacher-name'))
        output = str(logger.error.call_args)
        for secret in ('sk-secret', 'student@example.com', 'personal topic', 'teacher-name'):
            self.assertNotIn(secret, output)
        logger.exception.assert_not_called()
