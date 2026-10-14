import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from config.diagnostics import meta_response_directory
from services.ai import create_lesson, AIServiceError
from services.lesson_validation import normalize_meta_lesson, LessonValidationError
from services.meta_diagnostics import record_meta_response
from test_meta_structural_validation import ios


class MetaResponseCaptureTest(unittest.TestCase):
    def test_capture_requires_explicit_local_flag(self):
        for settings in ({}, {'LESSONAI_ENV': 'development'},
                         {'LESSONAI_ENV': 'production', 'LESSONAI_META_CAPTURE_RESPONSES': '1'}):
            with patch.dict(os.environ, settings, clear=True):
                self.assertIsNone(meta_response_directory())
                self.assertIsNone(record_meta_response(ios(), 'ai_raw', 'a' * 32))
        with patch.dict(os.environ, {'LESSONAI_ENV': 'local', 'LESSONAI_META_CAPTURE_RESPONSES': '1'}, clear=True):
            self.assertEqual(meta_response_directory().parts[-4:], ('docs', 'qa', 'meta', 'debug'))

    @patch('services.ai.openai_generate')
    def test_success_pair_preserves_original_and_normalized_scores_without_pii(self, provider):
        raw = ios()
        raw['assessment_items'][-1]['points'] = 15
        identity = 'Teacher Name student@example.com sk-secret-token'
        raw['teacher'] = identity
        raw['lesson_stages'][1]['tasks'][0]['name'] = identity
        raw['assessment_items'][0]['descriptors'][0]['action'] = identity
        provider.return_value = json.dumps(raw)
        with tempfile.TemporaryDirectory() as directory, patch('services.meta_diagnostics.meta_response_directory', return_value=Path(directory)):
            generated = create_lesson('Мобильная разработка', 'iOS', 'Русский', 'IT', 'Chair', 'Новый урок', 70, None,
                                      college='META', lesson_date=date(2026, 10, 13))
            provider.assert_called_once()
            files = list(Path(directory).glob('*.json'))
            self.assertEqual(len(files), 2)
            snapshots = {json.loads(path.read_text())['phase']: json.loads(path.read_text()) for path in files}
            self.assertEqual(snapshots['ai_raw']['summary']['actual_points_total'], 95)
            self.assertEqual(snapshots['normalized']['summary']['actual_points_total'], 100)
            self.assertEqual(snapshots['ai_raw']['attempt_id'], snapshots['normalized']['attempt_id'])
            self.assertEqual(snapshots['normalized']['attempt_id'], json.loads(generated)['meta_attempt_id'])
            for path in files:
                text = path.read_text()
                for secret in ('Teacher Name', 'student@example.com', 'sk-secret-token'): self.assertNotIn(secret, text)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            result = normalize_meta_lesson(snapshots['ai_raw']['lesson'])
            self.assertEqual([i['points'] for i in result['assessment_items']], [21, 21, 21, 21, 16])
            normalize_meta_lesson(snapshots['normalized']['lesson'])

    @patch('services.ai.openai_generate')
    def test_failure_pair_retains_error_and_replays_unknown_id(self, provider):
        plan = ios()
        plan['assessment_items'][0]['task_id'] = 'unknown'
        provider.return_value = json.dumps(plan)
        with tempfile.TemporaryDirectory() as directory, patch('services.meta_diagnostics.meta_response_directory', return_value=Path(directory)):
            with self.assertRaises(AIServiceError):
                create_lesson('Мобильная разработка', 'iOS', 'Русский', 'IT', 'Chair', 'Новый урок', 70, None, college='META')
            files = list(Path(directory).glob('*.json'))
            self.assertEqual(len(files), 2)
            failed = next(json.loads(path.read_text()) for path in files if 'normalization_failed' in path.name)
            self.assertEqual(failed['error']['code'], 'unknown_task_id')
            with self.assertRaises(LessonValidationError) as replay: normalize_meta_lesson(failed['lesson'])
            self.assertEqual(replay.exception.code, 'unknown_task_id')
            provider.assert_called_once()

    def test_missing_weights_and_instruction_are_preserved_as_missing(self):
        from services.meta_diagnostics import anonymized_snapshot
        plan = ios()
        for item in plan['assessment_items']:
            item.pop('points')
            for descriptor in item['descriptors']: descriptor.pop('points')
        plan['lesson_stages'][1]['tasks'][0].pop('instruction')
        snapshot = anonymized_snapshot(plan, None, 'ai_raw')
        self.assertNotIn('points', snapshot['lesson']['assessment_items'][0])
        self.assertNotIn('instruction', snapshot['lesson']['lesson_stages'][1]['tasks'][0])
        result = normalize_meta_lesson(snapshot['lesson'])
        self.assertEqual(sum(i['points'] for i in result['assessment_items']), 100)

    def test_capture_io_failure_does_not_raise(self):
        with patch('services.meta_diagnostics.meta_response_directory', return_value=Path('/unused')), patch('pathlib.Path.mkdir', side_effect=OSError('private error')):
            self.assertIsNone(record_meta_response(ios(), 'ai_raw', 'a' * 32))

    def test_local_capture_has_bounded_attempt_count_and_no_orphan_output(self):
        with tempfile.TemporaryDirectory() as directory, patch('services.meta_diagnostics.meta_response_directory', return_value=Path(directory)):
            for number in range(20):
                Path(directory, f'meta-response-{number:032x}-ai_raw.json').write_text('{}')
            self.assertIsNone(record_meta_response(ios(), 'ai_raw', 'f' * 32))
            self.assertIsNone(record_meta_response(ios(), 'normalized', 'f' * 32))
            self.assertEqual(len(list(Path(directory).glob('*.json'))), 20)

