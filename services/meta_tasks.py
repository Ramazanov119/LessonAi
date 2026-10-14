"""Task references for META: declared IDs first, safe structural normalization."""
import re
import unicodedata

from services.lesson_validation import LessonValidationError

def normalized(text):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold()))


def _id(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not value.strip():
        raise LessonValidationError('Задание должно иметь непустой идентификатор.')
    return value.strip()


def declared_tasks(stages):
    registry = {}
    for stage in stages:
        tasks = stage.get('tasks', [])
        # Recover a common JSON variant without inventing tasks or making AI calls.
        if isinstance(tasks, dict):
            if 'id' in tasks or 'task_id' in tasks:
                tasks = [tasks]
            elif all(isinstance(value, dict) for value in tasks.values()):
                tasks = [{**value, 'id': value.get('id', key)} for key, value in tasks.items()]
            else:
                tasks = None
        if not isinstance(tasks, list):
            raise LessonValidationError('Задания этапа должны быть массивом объектов.')
        stage['tasks'] = tasks
    reserved = {str(t.get('id', t.get('task_id'))).strip()
                for stage in stages for t in stage['tasks'] if isinstance(t, dict) and ('id' in t or 'task_id' in t)}
    for stage in stages:
        for index, task in enumerate(stage['tasks'], 1):
            if not isinstance(task, dict):
                raise LessonValidationError('Некорректная структура задания этапа.')
            if 'id' not in task and 'task_id' not in task:
                base = f'meta_{stage["field_key"]}_{index}'
                candidate = base
                suffix = 2
                while candidate in reserved:
                    candidate = f'{base}_{suffix}'
                    suffix += 1
                task['id'] = candidate
                reserved.add(candidate)
            task['id'] = _id(task.get('id', task.get('task_id')))
            task['name'] = task.get('name', task.get('task_name'))
            if not isinstance(task['name'], str) or not task['name'].strip():
                raise LessonValidationError('Не заполнено название задания этапа.')
            task['name'] = task['name'].strip()
            task['instruction'] = task.get('instruction', task['name'])
            if not isinstance(task['instruction'], str) or not task['instruction'].strip():
                raise LessonValidationError('Не заполнена инструкция задания этапа.')
            if task['id'] in registry:
                raise LessonValidationError(f"Идентификатор задания повторяется: {task['id']}.", code="duplicate_task_id", task_id=task['id'])
            registry[task['id']] = (stage, task)
            # Declared tasks are real lesson activities and must appear in Word,
            # not merely exist as unattached assessment rows.
            if normalized(task['instruction']) not in normalized(stage['content']):
                if normalized(task['name']) in normalized(stage['content']) or normalized(task['name']) == normalized(task['instruction']):
                    line = task['instruction']
                else:
                    line = f"{task['name']}: {task['instruction']}"
                stage['content'] += '\n' + line
    return registry


def resolve_assessment_task(item, stages, registry):
    reference = item.get('task_id')
    stage_key = item.get('stage_key')
    if reference is not None:
        reference = _id(reference)
        if reference not in registry:
            raise LessonValidationError(f'В этапах урока нет задания с task_id={reference}.', code="unknown_task_id", task_id=reference)
        stage, task = registry[reference]
        if stage_key is not None and stage_key != stage['field_key']:
            raise LessonValidationError(f'Задание {reference} принадлежит этапу {stage["field_key"]}, а не указанному этапу.', code="wrong_task_stage", task_id=reference)
        return stage, task
    # Safe incomplete-structure recovery: one declared task in an explicit stage.
    # Names, keywords and sentence similarity never establish membership.
    matches = [(stage, task) for stage, task in registry.values() if stage['field_key'] == stage_key]
    if stage_key is not None and len(matches) == 1:
        return matches[0]
    code = 'ambiguous_task_reference' if len(matches) > 1 else 'missing_task_reference'
    raise LessonValidationError('Не заполнен task_id: укажите ссылку на объявленное задание нужного этапа. Для старого плана без структуры заданий требуется повторная генерация.', code=code)
