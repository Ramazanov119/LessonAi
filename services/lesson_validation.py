"""Deterministic META lesson validation shared by generation and export."""
import copy
import json
import re
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from config.colleges import get_college_config


class LessonValidationError(ValueError):
    def __init__(self, message, *, code="invalid_lesson", task_id=None, phase="normalization"):
        super().__init__(message)
        self.code = code
        self.task_id = task_id
        self.phase = phase


META_STAGE_KEYS = (
    "org_steps", "actualization", "theory", "practice", "homework", "assessment", "reflection"
)
STAGE_NAMES = {
    "ru": ("Организационный этап", "Актуализация знаний", "Формирование новых знаний",
           "Практическая работа", "Домашнее задание", "Подведение итогов и оценивание", "Рефлексия"),
    "kk": ("Ұйымдастыру кезеңі", "Білімді өзектендіру", "Жаңа білімді қалыптастыру",
           "Практикалық жұмыс", "Үй тапсырмасы", "Қорытындылау және бағалау", "Рефлексия"),
    "en": ("Preparation", "Prior knowledge", "New material", "Practical work",
           "Homework", "Summary and assessment", "Reflection"),
}
BLOOM_LEVELS = {
    "ru": ("Знание", "Понимание", "Применение", "Анализ", "Оценивание", "Создание"),
    "kk": ("Білу", "Түсіну", "Қолдану", "Талдау", "Бағалау", "Жасау"),
    "en": ("Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"),
}


def language_code(language):
    from services.lecture_localization import lecture_labels, LECTURE_LABELS
    labels = lecture_labels(language)
    return next(key for key, value in LECTURE_LABELS.items() if value is labels)


def almaty_today():
    return datetime.now(ZoneInfo("Asia/Almaty")).date()


def lesson_date_value(value=None):
    """Only caller metadata is authoritative; never read a date from AI content."""
    if value is None or value == "":
        return almaty_today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = re.sub(r"\s*ж\./г\.\s*$", "", str(value).strip())
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text).date()
    except ValueError as error:
        raise LessonValidationError("Некорректная дата занятия.") from error


def parse_lesson(content):
    if isinstance(content, dict):
        return copy.deepcopy(content)
    text = str(content).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        payload = json.loads(text)
    except (ValueError, TypeError) as error:
        raise LessonValidationError("План должен содержать корректный JSON.") from error
    if not isinstance(payload, dict):
        raise LessonValidationError("План должен быть JSON-объектом.")
    return payload


def _integer(value, label):
    if type(value) is not int or value < 0:
        raise LessonValidationError(f"{label}: требуется целое неотрицательное число.")
    return value


def _allocate(weights, total, minimum=0):
    """Largest remainder allocation; deterministic and preserves order/weights."""
    if not weights or total < minimum * len(weights):
        raise LessonValidationError("Невозможно корректно распределить время или баллы.")
    remaining = total - minimum * len(weights)
    adjusted = [max(0, value - minimum) for value in weights]
    if not sum(adjusted):
        adjusted = [1] * len(weights)
    denominator = sum(adjusted)
    values = [minimum + remaining * weight // denominator for weight in adjusted]
    order = sorted(range(len(weights)), key=lambda i: (-(remaining * adjusted[i] % denominator), i))
    for index in order[:total - sum(values)]:
        values[index] += 1
    return values


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise LessonValidationError(f"Не заполнено поле: {label}.")
    return value.strip()


def _belongs_to_task(value, task_id, label):
    reference = value.get('task_id')
    if reference is not None and str(reference).strip() != task_id:
        raise LessonValidationError(f"{label} ссылается на другое задание: {task_id}.",
                                    code="assessment_reference_mismatch", task_id=task_id)


def _descriptor(value, task_id):
    """Validate observable-action fields, not word overlap or semantic similarity."""
    if isinstance(value, str):
        # Preserve existing descriptions; the full sentence is an action statement.
        text = _text(value, 'Дескриптор')
        value = {'task_id': task_id, 'text': text, 'action': text}
    if not isinstance(value, dict):
        raise LessonValidationError('Дескриптор должен быть строкой или объектом.',
                                    code="invalid_descriptor", task_id=task_id)
    _belongs_to_task(value, task_id, 'Дескриптор')
    action = value.get('action', value.get('text'))
    if not isinstance(action, str) or not action.strip():
        raise LessonValidationError('У дескриптора не указано наблюдаемое действие.',
                                    code="missing_observable_action", task_id=task_id)
    if 'requires_result' in value and type(value['requires_result']) is not bool:
        raise LessonValidationError('Признак измеримого результата должен быть логическим значением.', code='invalid_descriptor_result_flag', task_id=task_id)
    result = value.get('result')
    if result is not None and (not isinstance(result, str) or not result.strip()):
        raise LessonValidationError('Некорректный наблюдаемый результат дескриптора.',
                                    code="invalid_descriptor_result", task_id=task_id)
    if value.get('requires_result') is True and not result:
        raise LessonValidationError('У измеримого дескриптора не указан результат.',
                                    code="missing_descriptor_result", task_id=task_id)
    text = value.get('text')
    if text is None:
        text = action.strip() + (': ' + result.strip() if result else '')
    text = _text(text, 'Дескриптор')
    if re.search(r"\d+\s*(?:балл|ұпай|points?)", text, re.I):
        raise LessonValidationError('Баллы дескрипторов должны храниться отдельно от текста.',
                                    code="embedded_descriptor_points", task_id=task_id)
    detail = {'task_id': task_id, 'text': text, 'action': action.strip()}
    if result:
        detail['result'] = result.strip()
    if 'requires_result' in value:
        detail['requires_result'] = value['requires_result']
    from services.meta_scores import weight
    score = weight(value['points'], task_id=task_id) if 'points' in value else None
    return detail, score


def _normalize_meta_lesson(content, *, language="Русский", lesson_type="", lesson_date=None, context):
    payload = parse_lesson(content)
    duration = get_college_config("META")["lesson_duration"]
    lang = language_code(language)
    stages = payload.get("lesson_stages")
    if not stages:
        # Compatibility with saved plans: recover seven real template stages.
        weights = [5, 10, 20, 25, 3, 4, 3]
        if any(word in lesson_type.casefold() for word in ("практ", "лабор", "practical", "laboratory", "зертхан")):
            weights = [5, 5, 10, 40, 3, 4, 3]
        stages = []
        for i, key in enumerate(META_STAGE_KEYS):
            raw = payload.get(f"time{i + 1}", weights[i])
            if isinstance(raw, str):
                match = re.fullmatch(r"\s*(\d+)\s*(?:мин\.?|минут\w*|min\.?|minutes|минут|минуттар)?\s*", raw)
                if not match:
                    raise LessonValidationError(f"Некорректный time{i + 1}.")
                raw = int(match.group(1))
            stages.append({"field_key": key, "name": STAGE_NAMES[lang][i],
                           "duration_minutes": raw, "content": payload.get(key, "")})
    if not isinstance(stages, list) or not stages:
        raise LessonValidationError("Не заполнены этапы занятия.")
    seen = set()
    for stage in stages:
        if not isinstance(stage, dict):
            raise LessonValidationError("Некорректный этап занятия.")
        key = stage.get("field_key")
        if key not in META_STAGE_KEYS or key in seen:
            raise LessonValidationError("Этапы должны ссылаться на уникальные поля META-плана.")
        seen.add(key)
        stage["name"] = _text(stage.get("name"), "Название этапа")
        stage["content"] = _text(stage.get("content"), "Содержание этапа")
        _integer(stage.get("duration_minutes"), "Продолжительность этапа")
    from services.meta_tasks import declared_tasks, resolve_assessment_task
    registry = declared_tasks(stages)
    minutes = [stage["duration_minutes"] for stage in stages]
    if sum(minutes) != duration or min(minutes) < 1:
        minutes = _allocate(minutes, duration, minimum=1)
    for stage, value in zip(stages, minutes):
        stage["duration_minutes"] = value
        payload[stage["field_key"]] = stage["content"]
    for i, key in enumerate(META_STAGE_KEYS, 1):
        payload[f"time{i}"] = next((s["duration_minutes"] for s in stages if s["field_key"] == key), 0)
    payload["lesson_stages"] = stages
    payload["lesson_duration"] = duration

    items = payload.get("assessment_items")
    if not isinstance(items, list) or not items:
        raise LessonValidationError("В META-плане нет таблицы оценивания. Создайте план заново.")
    assessed = set()
    for item in items:
        if not isinstance(item, dict):
            raise LessonValidationError("Некорректная строка оценивания.")
        context["task_id"] = item.get("task_id")
        linked, task = resolve_assessment_task(item, stages, registry)
        task_id = task['id']
        context['task_id'] = task_id
        if task_id in assessed:
            raise LessonValidationError(f"Задание оценено повторно: {task_id}.", code="duplicate_assessment", task_id=task_id)
        assessed.add(task_id)
        item["task_id"] = task_id
        item["stage_key"] = linked["field_key"]
        item["task_name"] = task['name']
        criterion = item.get("assessment_criterion")
        if isinstance(criterion, dict):
            _belongs_to_task(criterion, task_id, 'Критерий')
            criterion = criterion.get('text')
        item["assessment_criterion"] = _text(criterion, "Критерий оценивания")
        level = _text(item.get("bloom_level"), "Уровень Блума")
        if level.casefold() not in {x.casefold() for x in BLOOM_LEVELS[lang]}:
            raise LessonValidationError("Уровень Блума должен соответствовать языку занятия.")
        descriptors = item.get("descriptors")
        if not isinstance(descriptors, list) or not descriptors:
            raise LessonValidationError("Не заполнены дескрипторы.")
        details = item.get('descriptor_details')
        # Normalized stored plans retain explicit actions/results and references.
        if details is not None:
            if not isinstance(details, list) or len(details) != len(descriptors):
                raise LessonValidationError('Структура дескрипторов не соответствует текстам.', code="descriptor_structure_mismatch", task_id=task_id)
            for detail, text in zip(details, descriptors):
                if not isinstance(detail, dict) or detail.get('text') != text:
                    raise LessonValidationError('Текст дескриптора противоречит его структуре.', code="descriptor_structure_mismatch", task_id=task_id)
            descriptors = details
        normalized = [_descriptor(value, task_id) for value in descriptors]
        item['descriptors'] = [detail['text'] for detail, _ in normalized]
        item['descriptor_details'] = [detail for detail, _ in normalized]
        item['_descriptor_weights'] = [score for _, score in normalized]
    from services.meta_scores import normalize_assessment_points
    context['task_id'] = None
    normalize_assessment_points(items, lang)
    context['task_id'] = None
    declared_tasks(stages)
    for stage in stages:
        payload[stage['field_key']] = stage['content']
    payload['evaluation_criteria'] = '\n'.join(dict.fromkeys(item['assessment_criterion'] for item in items))
    selected_date = lesson_date_value(lesson_date)
    payload.update(date=selected_date.isoformat(), data=selected_date.isoformat(), lesson_date=selected_date.isoformat())
    payload['meta_schema_version'] = 1
    payload['meta_attempt_id'] = uuid.uuid4().hex
    validate_meta_lesson(payload, language=language)
    return payload


def normalize_meta_lesson(content, *, language="Русский", lesson_type="", lesson_date=None):
    payload = parse_lesson(content)
    if payload.get('meta_schema_version') == 1:
        validate_meta_lesson(payload, language=language)
        selected = lesson_date_value(lesson_date if lesson_date is not None else payload.get('lesson_date'))
        payload.update(date=selected.isoformat(), data=selected.isoformat(), lesson_date=selected.isoformat())
        return payload
    context = {}
    try:
        return _normalize_meta_lesson(content, language=language, lesson_type=lesson_type,
                                      lesson_date=lesson_date, context=context)
    except LessonValidationError as error:
        if error.task_id is None:
            error.task_id = context.get('task_id')
        raise


def validate_meta_lesson(payload, *, language='Русский'):
    """Final, read-only check of the canonical model; never reallocates scores."""
    from services.meta_tasks import declared_tasks, resolve_assessment_task
    stages = payload.get('lesson_stages')
    if not isinstance(stages, list) or not stages or any(not isinstance(s, dict) for s in stages):
        raise LessonValidationError('Не заполнены этапы META.', code='invalid_stages')
    keys = [s.get('field_key') for s in stages]
    if any(key not in META_STAGE_KEYS for key in keys) or len(set(keys)) != len(keys):
        raise LessonValidationError('Этапы META должны иметь уникальные известные ключи.', code='invalid_stages')
    for stage in stages:
        _text(stage.get('name'), 'Название этапа')
        _text(stage.get('content'), 'Содержание этапа')
        tasks = stage.get('tasks')
        if not isinstance(tasks, list):
            raise LessonValidationError('Некорректная каноническая структура заданий.', code='invalid_task_structure')
        for task in tasks:
            if not isinstance(task, dict) or not isinstance(task.get('id'), str) or not task['id'].strip() or task['id'] != task['id'].strip():
                raise LessonValidationError('У задания отсутствует канонический task_id.', code='invalid_task_structure')
            _text(task.get('name'), 'Название задания')
            _text(task.get('instruction'), 'Инструкция задания')
        if payload.get(stage['field_key']) != stage['content']:
            raise LessonValidationError('Содержание этапа противоречит канонической модели.', code='stage_content_mismatch')
        if _integer(stage.get('duration_minutes'), 'Время этапа') < 1:
            raise LessonValidationError('Этап должен длиться хотя бы минуту.', code='invalid_duration')
    if sum(s['duration_minutes'] for s in stages) != 70 or payload.get('lesson_duration') != 70:
        raise LessonValidationError('Сумма времени META должна быть 70 минут.', code='duration_total')
    source_copy = copy.deepcopy(stages)
    registry = declared_tasks(source_copy)
    if any(original['content'] != normalized['content'] for original, normalized in zip(stages, source_copy)):
        raise LessonValidationError('Задание не включено в содержимое канонического этапа.', code='stage_task_content_mismatch')
    items = payload.get('assessment_items')
    if not isinstance(items, list) or not items:
        raise LessonValidationError('Не заполнено оценивание.', code='missing_assessment')
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise LessonValidationError('Некорректное оценивание.', code='invalid_assessment')
        stage, task = resolve_assessment_task(item, stages, registry)
        reference = task['id']
        if reference in seen:
            raise LessonValidationError('Задание оценено повторно.', code='duplicate_assessment', task_id=reference)
        seen.add(reference)
        if item.get('task_id') != reference or item.get('stage_key') != stage['field_key'] or item.get('task_name') != task['name']:
            raise LessonValidationError('Каноническая ссылка задания противоречива.', code='assessment_reference_mismatch', task_id=reference)
        _text(item.get('assessment_criterion'), 'Критерий оценивания')
        level = item.get('bloom_level')
        if not isinstance(level, str) or level.casefold() not in {v.casefold() for v in BLOOM_LEVELS[language_code(language)]}:
            raise LessonValidationError('Некорректный уровень Блума.', task_id=reference)
        descriptors, details, points = item.get('descriptors'), item.get('descriptor_details'), item.get('descriptor_points')
        if not isinstance(descriptors, list) or not descriptors or not isinstance(details, list) or len(details) != len(descriptors):
            raise LessonValidationError('Несогласованная структура дескрипторов.', code='descriptor_structure_mismatch', task_id=reference)
        for text, detail in zip(descriptors, details):
            if not isinstance(detail, dict) or detail.get('text') != text:
                raise LessonValidationError('Тексты дескрипторов противоречат структуре.', code='descriptor_structure_mismatch', task_id=reference)
            _descriptor(detail, reference)
        maximum = _integer(item.get('points'), 'Баллы задания')
        low, high = item.get('points_min', 1), item.get('points_max', 100)
        if type(low) is not int or type(high) is not int or low < 0 or high < low or maximum < 1 or not low <= maximum <= high:
            raise LessonValidationError('Баллы задания вне границ.', code='impossible_score_allocation', task_id=reference)
        if not isinstance(points, list) or len(points) != len(descriptors) or sum(_integer(p, 'Баллы дескриптора') for p in points) != maximum:
            raise LessonValidationError('Сумма баллов дескрипторов не равна баллу задания.', code='descriptor_points_total', task_id=reference)
    total = sum(item['points'] for item in items)
    if total != 100:
        raise LessonValidationError(f'Сумма баллов META: {total}; требуется 100. Баллы заданий: {[i["points"] for i in items]}.', code='assessment_points_total')
    if payload.get('evaluation_criteria') != '\n'.join(dict.fromkeys(item['assessment_criterion'] for item in items)):
        raise LessonValidationError('Критерии шаблона противоречат таблице оценивания.', code='criteria_structure_mismatch')
    return payload
