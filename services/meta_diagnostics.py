"""Save structural, text-free snapshots only: no raw AI response or identity data."""
import hashlib
import json
import logging
import math
import re
import os
import uuid
from pathlib import Path

from config.diagnostics import meta_diagnostic_directory, meta_response_directory


def validation_error(error):
    from services.lesson_validation import LessonValidationError
    current = error
    for _ in range(4):
        if isinstance(current, LessonValidationError):
            return current
        current = getattr(current, '__cause__', None)
        if current is None:
            break
    return error


def failure_metadata(error):
    error = validation_error(error)
    reference = getattr(error, 'task_id', None)
    return {'error_type': type(error).__name__, 'code': getattr(error, 'code', 'operation_failed'),
            'task_token': hashlib.sha256(str(reference).encode()).hexdigest()[:12] if reference is not None else None,
            'phase': getattr(error, 'phase', None)}


def anonymized_snapshot(content, error, phase):
    from services.lesson_validation import META_STAGE_KEYS, BLOOM_LEVELS, parse_lesson
    tokens = {}
    def task_id(value):
        if value is None:
            return None
        # Preserve structural identity, never the original ID (which could contain PII).
        key = str(value)
        if key not in tokens:
            tokens[key] = f'task_{len(tokens) + 1:03d}'
        return tokens[key]
    def text(value):
        if value is None:
            return None
        if not isinstance(value, str):
            return {'invalid_type': type(value).__name__}
        return 'Наблюдаемое действие' if value.strip() else ''
    def number(value):
        try:
            valid = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            valid = False
        return value if valid else {'invalid_type': type(value).__name__}
    def stage_key(value):
        return value if value in META_STAGE_KEYS else '[unknown_stage]'
    try:
        payload = parse_lesson(content)
    except (TypeError, ValueError):
        payload = {}
    lesson = {'lesson_duration': number(payload.get('lesson_duration'))} if isinstance(payload, dict) else {}
    if isinstance(payload, dict):
        if payload.get('meta_schema_version') == 1: lesson['meta_schema_version'] = 1
        stages = []
        for source in payload.get('lesson_stages', []) if isinstance(payload.get('lesson_stages'), list) else []:
            if not isinstance(source, dict):
                stages.append({'invalid_type': type(source).__name__}); continue
            tasks = source.get('tasks', [])
            if isinstance(tasks, dict):
                tasks = [tasks] if 'id' in tasks or 'task_id' in tasks else [{**v, 'id': v.get('id', k)} for k, v in tasks.items() if isinstance(v, dict)]
            stages.append({'field_key': stage_key(source.get('field_key')), 'name': text(source.get('name')),
                           'duration_minutes': number(source.get('duration_minutes')), 'content': text(source.get('content')),
                           'tasks': [{**({'id': task_id(t.get('id', t.get('task_id')))} if 'id' in t or 'task_id' in t else {}), 'name': text(t.get('name', t.get('task_name'))),
                                      **({'instruction': text(t['instruction'])} if 'instruction' in t else {})} for t in tasks if isinstance(t, dict)] if isinstance(tasks, list) else None})
        lesson['lesson_stages'] = stages
        if lesson.get('meta_schema_version') == 1:
            lesson.update({s['field_key']: s['content'] for s in stages if s.get('field_key') in META_STAGE_KEYS})
        items = []
        for source in payload.get('assessment_items', []) if isinstance(payload.get('assessment_items'), list) else []:
            if not isinstance(source, dict):
                items.append({'invalid_type': type(source).__name__}); continue
            criterion = source.get('assessment_criterion')
            criterion = {'task_id': task_id(criterion.get('task_id')), 'text': text(criterion.get('text'))} if isinstance(criterion, dict) else text(criterion)
            def descriptor_list(values):
                descriptors = []
                for value in values if isinstance(values, list) else []:
                    if not isinstance(value, dict):
                        descriptors.append(text(value)); continue
                    descriptor = {key: text(value[key]) for key in ('text', 'action', 'result') if key in value}
                    if 'task_id' in value: descriptor['task_id'] = task_id(value['task_id'])
                    if 'points' in value: descriptor['points'] = number(value['points'])
                    if 'requires_result' in value:
                        descriptor['requires_result'] = value['requires_result'] if type(value['requires_result']) is bool else {'invalid_type': type(value['requires_result']).__name__}
                    descriptors.append(descriptor)
                return descriptors
            descriptors = descriptor_list(source.get('descriptors'))
            bloom = source.get('bloom_level')
            items.append({'task_id': task_id(source.get('task_id')), 'stage_key': stage_key(source.get('stage_key')),
                          'task_name': text(source.get('task_name')), 'bloom_level': bloom if isinstance(bloom, str) and bloom in set().union(*map(set, BLOOM_LEVELS.values())) else '[invalid_level]',
                          'assessment_criterion': criterion, 'descriptors': descriptors})
            if 'points' in source: items[-1]['points'] = number(source['points'])
            if isinstance(source.get('descriptor_points'), list):
                items[-1]['descriptor_points'] = [number(value) for value in source['descriptor_points']]
            if 'descriptor_details' in source:
                items[-1]['descriptor_details'] = descriptor_list(source['descriptor_details'])
            for key in ('points_min', 'points_max'):
                if key in source: items[-1][key] = number(source[key])
        lesson['assessment_items'] = items
        if lesson.get('meta_schema_version') == 1:
            lesson['evaluation_criteria'] = '\n'.join(dict.fromkeys(i['assessment_criterion'] for i in items if isinstance(i.get('assessment_criterion'), str)))
    actual = validation_error(error)
    attempt = payload.get('meta_attempt_id')
    attempt = attempt if isinstance(attempt, str) and re.fullmatch('[a-f0-9]{32}', attempt) else uuid.uuid4().hex
    score_rows = [{'task_id': item.get('task_id'), 'points': item.get('points')} for item in lesson.get('assessment_items', [])]
    scores = [row['points'] for row in score_rows]
    summary = {'actual_points_total': sum(scores) if all(type(v) in (int, float) for v in scores) else None,
               'points_by_task': score_rows, 'stage_count': len(lesson.get('lesson_stages', [])),
               'task_count': sum(len(s.get('tasks') or []) for s in lesson.get('lesson_stages', [])),
               'assessment_count': len(score_rows)}
    return {'schema_version': 1, 'attempt_id': attempt, 'phase': phase, 'summary': summary, 'error': {'type': type(actual).__name__,
            'code': getattr(actual, 'code', 'operation_failed'), 'task_id': task_id(getattr(actual, 'task_id', None))},
            'text_policy': 'All free text, metadata and original IDs removed', 'lesson': lesson}


def record_meta_failure(content, error, phase):
    directory = meta_diagnostic_directory()
    if directory is None or getattr(error, '_meta_diagnostic_recorded', False):
        return None
    try:
        snapshot = anonymized_snapshot(content, error, phase)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if len(list(directory.glob('meta-failure-*.json'))) >= 20:
            return None
        path = directory / ('meta-failure-' + uuid.uuid4().hex + '.json')
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as file:
            json.dump(snapshot, file, ensure_ascii=False, indent=2)
        error._meta_diagnostic_recorded = True
        return path
    except Exception:
        # Diagnostics must never mask the original rejection or store a raw fallback.
        logging.getLogger(__name__).warning('META structural diagnostic unavailable')
        return None


def record_meta_response(content, phase, attempt_id, error=None):
    """Capture original structure and canonical structure, never raw private text."""
    directory = meta_response_directory()
    if directory is None:
        return None
    if phase not in ('ai_raw', 'normalized', 'normalization_failed') or not re.fullmatch('[a-f0-9]{32}', attempt_id):
        return None
    try:
        snapshot = anonymized_snapshot(content, error, phase)
        snapshot['attempt_id'] = attempt_id
        if error is None:
            snapshot['error'] = None
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        # At most twenty attempts, each up to three structural snapshots.
        path = directory / f'meta-response-{attempt_id}-{phase}.json'
        if len(list(directory.glob('meta-response-*-ai_raw.json'))) >= 20 and phase == 'ai_raw':
            return None
        if phase != 'ai_raw' and not (directory / f'meta-response-{attempt_id}-ai_raw.json').exists():
            return None
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as file:
            json.dump(snapshot, file, ensure_ascii=False, indent=2, allow_nan=False)
        return path
    except FileExistsError:
        return None
    except Exception:
        logging.getLogger(__name__).warning('META structural response capture unavailable')
        return None
