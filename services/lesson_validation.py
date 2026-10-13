"""Deterministic META lesson validation shared by generation and export."""
import copy
import json
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from config.colleges import get_college_config


class LessonValidationError(ValueError):
    pass


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


# A conservative topical check complements exact task/stage references. It does
# not attempt to prove pedagogical correctness or replace instructor review.
_COMMON_WORDS = """задание задания выполняет выполнение студент студенты обучающийся
обучающиеся определяет объясняет правильно корректно показывает демонстрирует
понимание понимает анализирует использует применяет называет формулирует
тапсырма тапсырманы орындайды білім алушылар анықтайды түсіндіреді дұрыс
қолданады көрсетеді талдайды жазады студенттер
student students task tasks completes identifies explains correctly demonstrates
understands analyzes uses applies describes defines"""
_COMMON_STEMS = {word[:4] for word in _COMMON_WORDS.split()}


def _topic_stems(text):
    return {word[:4] for word in re.findall(r"[^\W\d_]+", text.casefold())
            if len(word) >= 4 and word[:4] not in _COMMON_STEMS}


def _check_relevance(text, context, label):
    if not (_topic_stems(text) & _topic_stems(context)):
        raise LessonValidationError(f"{label} не содержит терминов задания и его этапа: {text}")


def normalize_meta_lesson(content, *, language="Русский", lesson_type="", lesson_date=None):
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
        task = _text(item.get("task_name"), "Задание")
        key = item.get("stage_key")
        candidates = [s for s in stages if key is None or s["field_key"] == key]
        linked = next((s for s in candidates if task.casefold() in s["content"].casefold()), None)
        if linked is None or task.casefold() in assessed:
            raise LessonValidationError(f"Задание отсутствует в этапе урока или повторяется: {task}")
        assessed.add(task.casefold())
        item["stage_key"] = linked["field_key"]
        item["task_name"] = task
        item["assessment_criterion"] = _text(item.get("assessment_criterion"), "Критерий оценивания")
        _check_relevance(item["assessment_criterion"], linked["content"], "Критерий")
        level = _text(item.get("bloom_level"), "Уровень Блума")
        if level.casefold() not in {x.casefold() for x in BLOOM_LEVELS[lang]}:
            raise LessonValidationError("Уровень Блума должен соответствовать языку занятия.")
        descriptors = item.get("descriptors")
        if not isinstance(descriptors, list) or not descriptors:
            raise LessonValidationError("Не заполнены дескрипторы.")
        texts, scores = [], []
        for descriptor in descriptors:
            if isinstance(descriptor, dict):
                texts.append(_text(descriptor.get("text"), "Дескриптор"))
                scores.append(_integer(descriptor.get("points"), "Балл дескриптора"))
            else:
                texts.append(_text(descriptor, "Дескриптор"))
                scores.append(1)
            _check_relevance(texts[-1], linked["content"], "Дескриптор")
            if re.search(r"\d+\s*(?:балл|ұпай|points?)", texts[-1], re.I):
                raise LessonValidationError("Баллы дескрипторов должны храниться отдельно от текста.")
        item["descriptors"] = texts
        existing_scores = item.get("descriptor_points", scores)
        if not isinstance(existing_scores, list) or len(existing_scores) != len(texts):
            raise LessonValidationError("Баллы дескрипторов не соответствуют дескрипторам.")
        item["descriptor_points"] = [_integer(x, "Балл дескриптора") for x in existing_scores]
        _integer(item.get("points"), "Максимальный балл задания")
    points = [item["points"] for item in items]
    if sum(points) != 100:
        points = _allocate(points, 100)
    for item, value in zip(items, points):
        item["points"] = value
        scores = item["descriptor_points"]
        if sum(scores) != value:
            item["descriptor_points"] = _allocate(scores, value)
    selected_date = lesson_date_value(lesson_date)
    payload.update(date=selected_date.isoformat(), data=selected_date.isoformat(), lesson_date=selected_date.isoformat())
    return payload
