"""Q College's optional interdisciplinary section, using the existing lesson field."""
import re
from services.lesson_validation import LessonValidationError, language_code, parse_lesson

LABELS = {'ru': 'Межпредметные связи:', 'kk': 'Пәнаралық байланыс:', 'en': 'Interdisciplinary links:'}


def q_connections(content):
    payload = parse_lesson(content)
    value = payload.get('interdisciplinary_connections') or payload.get('interdisciplinary_links')
    if not isinstance(value, str) or not value.strip():
        raise LessonValidationError('В плане Q не заполнены межпредметные связи. Создайте план заново.')
    value = value.strip()
    entries = [item.strip() for item in re.split(r';|\n', value) if item.strip()]
    if not 1 <= len(entries) <= 3:
        raise LessonValidationError('Для Q нужны 1–3 межпредметные связи с пояснениями.')
    for entry in entries:
        parts = re.split(r'\s*[—–:]\s*|\s+-\s+', entry, maxsplit=1)
        if len(parts) != 2 or not all(part.strip() for part in parts):
            raise LessonValidationError('Укажите для каждой дисциплины используемые знания или навыки.')
    return value


def q_template_fields(content, language='Русский'):
    return {'q_interdisciplinary_label': LABELS[language_code(language)],
            'interdisciplinary_connections': q_connections(content)}


def localize_q_section(doc, language):
    from services.meta_docx import set_cell_text
    matches = [row for table in doc.tables for row in table.rows if
               row.cells[0].text.strip() in set(LABELS.values()) | {'{q_interdisciplinary_label}'}]
    if len(matches) != 1:
        raise LessonValidationError('В шаблоне Q должна быть одна строка межпредметных связей.')
    set_cell_text(matches[0].cells[0], LABELS[language_code(language)])
