import json
import re
from datetime import date, datetime
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Inches, Pt

from config.colleges import get_college_config
from services.lecture_localization import lecture_labels
from services.lesson_validation import lesson_date_value, normalize_meta_lesson
from services.meta_docx import fill_meta_tables
from services.meta_localization import meta_labels
from services.meta_formatting import dynamic_run_font
from services.q_docx import q_template_fields, localize_q_section
from services.document_style import (
    add_page_number,
    configure_document,
    normalize_document_fonts,
    normalize_paragraph,
    set_run_font,
)


LESSON_TEMPLATE = get_college_config("ETEC")["template"]


def _add_block(doc, title, body):
    doc.add_heading(title, level=2)
    para = doc.add_paragraph()
    run = para.add_run(str(body))
    set_run_font(run)
    normalize_paragraph(para)


def _get_logo_path(college):
    logo_path = get_college_config(college)["logo"]
    return logo_path if logo_path.exists() else None


def _add_title_page(
    doc,
    *,
    language="Русский",
    college=None,
    subject=None,
    title=None,
    teacher=None,
    group=None,
    course=None,
    lesson_date=None,
):
    labels = lecture_labels(language)
    logo_path = _get_logo_path(college)

    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    title_para.paragraph_format.space_after = Pt(10)

    if logo_path:
        try:
            title_para.add_run().add_picture(
                str(logo_path),
                width=Inches(2.2),
            )
        except Exception:
            pass

    meta = [
        (labels["teacher"], teacher or ""),
        (
            labels["date"],
            lesson_date.strftime("%d.%m.%Y")
            if lesson_date
            else "",
        ),
    ]

    for label, value in meta:
        if not value:
            continue

        line = doc.add_paragraph()
        line.alignment = WD_ALIGN_PARAGRAPH.LEFT
        line.paragraph_format.space_after = Pt(3)

        label_run = line.add_run(f"{label}: ")
        label_run.bold = True
        set_run_font(label_run)

        value_run = line.add_run(str(value))
        set_run_font(value_run)

    subject_text = str(subject or labels["subject"])

    subject_para = doc.add_paragraph()
    subject_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subject_para.paragraph_format.space_before = Pt(48)
    subject_para.paragraph_format.space_after = Pt(8)

    subject_run = subject_para.add_run(subject_text)
    set_run_font(subject_run, Pt(16), bold=True)

    type_para = doc.add_paragraph()
    type_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    type_para.paragraph_format.space_after = Pt(8)

    type_run = type_para.add_run(labels["lecture"].upper())
    set_run_font(type_run, Pt(16), bold=True)

    lecture_title = str(title or labels["lecture"])

    lecture_para = doc.add_paragraph()
    lecture_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    lecture_para.paragraph_format.space_after = Pt(0)

    lecture_run = lecture_para.add_run(lecture_title)
    set_run_font(lecture_run, Pt(16), bold=True)

    doc.add_page_break()


def _add_list_item(doc, text, level=0):
    style_name = "List Bullet" if level == 0 else "List Bullet 2"

    if style_name not in doc.styles:
        style_name = "List Bullet"

    paragraph = doc.add_paragraph(style=style_name)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.paragraph_format.first_line_indent = Cm(0)

    paragraph.add_run(str(text))

    for run in paragraph.runs:
        set_run_font(run)


def _add_info_box(doc, title, content):
    doc.add_heading(title, level=2)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.style = "Intense Quote"

    run = p.add_run(str(content))
    set_run_font(run)

    normalize_paragraph(p)


def _strip_json_block(text):
    if not isinstance(text, str):
        return text

    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = (
            cleaned
            .split("\n", 1)[-1]
            .rsplit("```", 1)[0]
            .strip()
        )

    return cleaned


def _lesson_fields(content):
    if isinstance(content, dict):
        return content

    try:
        parsed = json.loads(_strip_json_block(content))
    except (TypeError, json.JSONDecodeError):
        return {"theory": content}

    return (
        parsed
        if isinstance(parsed, dict)
        else {"theory": content}
    )


def _format_date_value(value):
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%d.%m.%Y")
    if not isinstance(value, str):
        return str(value)

    text = value.strip()
    if not text:
        return ""

    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y.%m.%d",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(text, fmt).strftime("%d.%m.%Y")
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text).strftime("%d.%m.%Y")
    except ValueError:
        pass

    return text


def _field_value(key, value):
    if value is None:
        return ""
    key_name = str(key).lower()
    if key_name in {"date", "data", "lesson_date"}:
        return _format_date_value(value)
    return str(value)


def _replace_placeholders(paragraph, fields, *, meta_font=False):
    if not fields:
        return
    runs = list(paragraph.runs)
    text = "".join(run.text for run in runs)
    offsets = []
    position = 0
    for run in runs:
        offsets.append((position, position + len(run.text)))
        position += len(run.text)
    pattern = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}|\{([a-zA-Z0-9_]+)\}")
    applied = False
    for match in reversed(list(pattern.finditer(text))):
        key = match.group(1) or match.group(2)
        if key not in fields:
            continue
        applied = True
        replacement = _field_value(key, fields[key])
        first = True
        for run, (start, end) in zip(runs, offsets):
            if end <= match.start() or start >= match.end():
                continue
            left = max(0, match.start() - start)
            right = min(end - start, match.end() - start)
            run.text = run.text[:left] + (replacement if first else "") + run.text[right:]
            first = False
    if applied and meta_font:
        for run in paragraph.runs:
            dynamic_run_font(run)


def _document_paragraphs(doc):
    # XML traversal includes nested tables, headers, footers and text boxes.
    from docx.text.paragraph import Paragraph
    parts = [doc._element]
    # Inspect existing parts only: accessing an undefined section header would
    # create a new blank header and change the source template.
    for part in doc.part.related_parts.values():
        if part.content_type.endswith(("wordprocessingml.header+xml", "wordprocessingml.footer+xml")):
            parts.append(part._element)
    seen = set()
    for part in parts:
        for element in part.xpath('.//w:p'):
            if element not in seen:
                seen.add(element)
                yield Paragraph(element, doc)


def _fill_document(doc, fields, *, meta_font=False):
    for paragraph in _document_paragraphs(doc):
        _replace_placeholders(paragraph, fields, meta_font=meta_font)


def _meta_template_fields(content):
    """
    Prepare the fields used by the META lesson-plan template.

    The original lesson fields are not removed. These fields are
    additionally prepared for the template so that META-specific
    placeholders can be filled without breaking the existing ETEC
    generation flow.
    """
    payload = _lesson_fields(content)

    return {
        # Организационный этап
        "time1": payload.get("time1", ""),
        "org_steps": payload.get("org_steps", ""),

        # Актуализация
        "time2": payload.get("time2", ""),
        "actualization": payload.get("actualization", ""),
        "actualization_resource": payload.get(
            "actualization_resource",
            "",
        ),

        # Теория
        "time3": payload.get("time3", ""),
        "theory": payload.get("theory", ""),
        "presentation_demo": payload.get(
            "presentation_demo",
            "",
        ),

        # Практика
        "time4": payload.get("time4", ""),
        "practice": payload.get("practice", ""),
        "practice_result": payload.get(
            "practice_result",
            "",
        ),

        # Взаимооценивание
        "time5": payload.get("time5", ""),
        "peer_assessment": payload.get(
            "peer_assessment",
            "",
        ),

        # Рефлексия и оценивание
        "time6": payload.get("time6", ""),
        "reflection": payload.get("reflection", ""),
        "assessment": payload.get("assessment", ""),
        "assessment_sheet": payload.get(
            "assessment_sheet",
            "",
        ),

        # Домашнее задание
        "homework": payload.get("homework", ""),

        # Дополнительные поля шаблона
        "date": payload.get("date", payload.get("lesson_date", "")),
        "data": payload.get("date", payload.get("lesson_date", "")),
        "evaluation_criteria": payload.get(
            "evaluation_criteria",
            "",
        ),
        "explanatory_illustrative_method": payload.get(
            "explanatory_illustrative_method",
            payload.get("presentation_demo", ""),
        ),
        "practical_task": payload.get(
            "practical_task",
            payload.get("practice", ""),
        ),
        "interdisciplinary_connections": payload.get(
            "interdisciplinary_connections",
            payload.get("resources", ""),
        ),
        "resources": payload.get(
            "resources",
            "",
        ),
    }


def _save_template_document(doc, template_path):
    """Retain untouched template package parts byte-for-byte (styles/media/etc.)."""
    rendered = BytesIO()
    doc.save(rendered)
    result = BytesIO()
    from lxml import etree
    namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    def texts(xml):
        return etree.fromstring(xml).xpath('//w:t/text()', namespaces=namespaces)
    with ZipFile(template_path) as original, ZipFile(rendered) as generated, ZipFile(result, 'w') as output:
        for entry in original.infolist():
            name = entry.filename
            data = original.read(name)
            if name == 'word/document.xml':
                data = generated.read(name)
            elif name.startswith(('word/header', 'word/footer')) and name.endswith('.xml'):
                changed = generated.read(name)
                if texts(data) != texts(changed):
                    data = changed
            output.writestr(entry, data)
    result.seek(0)
    return result


def build_doc(
    title,
    content,
    schema=None,
    visual=None,
    template_path=LESSON_TEMPLATE,
    fields=None,
    college=None,
):
    if title == "План урока" and Path(template_path).exists():
        doc = Document(template_path)

        # Основные поля, которые уже существовали в проекте.
        template_fields = _lesson_fields(content)
        # The form/saved lesson date always wins over generated content.
        metadata = fields or {}
        selected_date = next((metadata[key] for key in ("lesson_date", "date", "data")
                              if metadata.get(key) not in (None, "")), None)
        formatted_date = lesson_date_value(selected_date).strftime("%d.%m.%Y")
        is_meta = str(college or "").upper() == "META" or Path(template_path).resolve() == get_college_config("META")["template"].resolve()
        if is_meta:
            template_fields = normalize_meta_lesson(
                content, language=metadata.get("language", "Русский"),
                lesson_type=metadata.get("lesson_type", ""), lesson_date=selected_date,
            )
            fill_meta_tables(doc, template_fields, metadata.get("language", "Русский"))

        is_q = str(college or "").upper() == "Q" or Path(template_path).resolve() == get_college_config("Q")["template"].resolve()
        q_fields = q_template_fields(template_fields, metadata.get("language", "Русский")) if is_q else {}
        if is_q:
            localize_q_section(doc, metadata.get("language", "Русский"))

        # Дополнительные поля META-шаблона.
        meta_fields = _meta_template_fields(template_fields)

        # Объединяем оба набора.
        #
        # template_fields сохраняет обратную совместимость
        # с существующим ETEC-шаблоном.
        #
        # meta_fields добавляет специальные поля META.
        #
        # fields имеет самый высокий приоритет, если какие-либо
        # значения передаются непосредственно в build_doc().
        all_fields = {
            **template_fields,
            **meta_fields,
            **(fields or {}),
            **q_fields,
        }

        if is_meta:
            labels = meta_labels(metadata.get("language", "Русский"))
            all_fields.update({key: labels[key] for key in ("explanatory_method_label", "practical_task_label")})

        all_fields.update(date=formatted_date, data=formatted_date,
                          lesson_date=formatted_date + (" ж./г." if is_meta else ""))
        _fill_document(doc, all_fields, meta_font=is_meta)
        # Preserve the original Word template structure and formatting; only
        # replace the placeholder text already present in the template.

    else:
        doc = Document()
        configure_document(doc)

        title_style = doc.styles["Normal"]
        title_style.font.name = "Times New Roman"
        title_style.font.size = Pt(11)

        doc.add_heading(title, 1)
        paragraph = doc.add_paragraph(content)
        normalize_paragraph(paragraph, size=Pt(11))
        normalize_document_fonts(doc)

    if schema and title != "План урока":
        doc.add_heading("Схема", 2)
        doc.add_paragraph(schema)

    if visual and title != "План урока":
        doc.add_heading("Иллюстрация", 2)
        doc.add_paragraph(visual)

    if title == "План урока" and Path(template_path).exists():
        return _save_template_document(doc, template_path)

    file = BytesIO()
    doc.save(file)
    file.seek(0)

    return file


def build_lecture_docx(
    lecture_text,
    title=None,
    *,
    language="Русский",
    college=None,
    subject=None,
    teacher=None,
    group=None,
    course=None,
    lesson_date=None,
):
    labels = lecture_labels(language)
    payload = _lesson_fields(lecture_text)

    doc = Document()
    configure_document(doc)

    _add_title_page(
        doc,
        language=language,
        college=college,
        subject=subject,
        title=title,
        teacher=teacher,
        group=group,
        course=course,
        lesson_date=lesson_date,
    )

    if payload.get("relevance"):
        doc.add_heading(labels["relevance"], level=1)

        paragraph = doc.add_paragraph(
            payload["relevance"]
        )
        normalize_paragraph(paragraph)

    if payload.get("learning_goals"):
        doc.add_heading(labels["learning_goals"], level=1)

        for item in payload["learning_goals"]:
            _add_list_item(doc, str(item))

    if payload.get("key_terms"):
        doc.add_heading(labels["key_terms"], level=1)

        for term in payload["key_terms"]:
            doc.add_heading(
                str(term.get("term", labels["term"])),
                level=2,
            )

            if term.get("definition"):
                paragraph = doc.add_paragraph(
                    str(term.get("definition", ""))
                )
                normalize_paragraph(paragraph)

    if payload.get("main_material"):
        doc.add_heading(
            labels["main_material"],
            level=1,
        )

        for section in payload["main_material"]:
            doc.add_heading(
                str(section.get("title", labels["material"])),
                level=2,
            )

            if section.get("content"):
                paragraph = doc.add_paragraph(
                    str(section.get("content", ""))
                )
                normalize_paragraph(paragraph)

            if section.get("examples"):
                doc.add_heading(labels["examples"], level=3)

                for example in section.get("examples", []):
                    _add_list_item(doc, str(example))

    if payload.get("practice_examples"):
        doc.add_heading(
            labels["practice_examples"],
            level=1,
        )

        for item in payload["practice_examples"]:
            _add_list_item(doc, str(item))

    if payload.get("case_study"):
        case = payload["case_study"]

        doc.add_heading(
            labels["case_study"],
            level=1,
        )

        _add_block(
            doc,
            labels["scenario"],
            case.get("scenario", ""),
        )

        _add_block(
            doc,
            labels["analysis"],
            case.get("analysis", ""),
        )

        _add_block(
            doc,
            labels["solution"],
            case.get("solution", ""),
        )

    if payload.get("common_errors"):
        doc.add_heading(
            labels["common_errors"],
            level=1,
        )

        for item in payload["common_errors"]:
            _add_block(
                doc,
                labels["error"],
                item.get("error", ""),
            )

            _add_block(
                doc,
                labels["why"],
                item.get("why", ""),
            )

            _add_block(
                doc,
                labels["fix"],
                item.get("fix", ""),
            )

    if payload.get("summary"):
        doc.add_heading(labels["summary"], level=1)

        for item in payload["summary"]:
            _add_list_item(doc, str(item))

    if payload.get("review_questions"):
        doc.add_heading(
            labels["review_questions"],
            level=1,
        )

        for index, item in enumerate(
            payload["review_questions"],
            start=1,
        ):
            paragraph = doc.add_paragraph(
                f"{index}. {item}"
            )
            normalize_paragraph(paragraph)

    if payload.get("preparation_for_practice"):
        doc.add_heading(
            labels["preparation_for_practice"],
            level=1,
        )

        paragraph = doc.add_paragraph(
            str(payload["preparation_for_practice"])
        )
        normalize_paragraph(paragraph)

    for section in doc.sections:
        para = section.footer.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.text = ""

        footer_label = para.add_run(labels["page"] + " ")
        set_run_font(
            footer_label,
            size=Pt(12),
        )

        add_page_number(para)

    normalize_document_fonts(doc)

    file = BytesIO()
    doc.save(file)
    file.seek(0)

    return file


def build_practice_docx(
    practice_text,
    title="Практическое занятие",
    *,
    college=None,
    subject=None,
    teacher=None,
    lesson_date=None,
):
    """Build a styled DOCX from the stored structured practice content."""

    payload = _lesson_fields(practice_text)

    doc = Document()
    configure_document(doc)

    _add_title_page(
        doc,
        college=college,
        subject=subject,
        title=title,
        teacher=teacher,
        lesson_date=lesson_date,
    )

    sections = (
        ("Цель", "objective"),
        ("Краткая теория", "brief_theory"),
        ("Профессиональная ситуация", "professional_context"),
        ("Практическое задание", "main_task"),
        ("Ожидаемый результат", "expected_result"),
        ("Заключение", "conclusion"),
    )

    doc.add_heading(
        str(payload.get("title", title)),
        level=1,
    )

    for heading, key in sections:
        if payload.get(key):
            doc.add_heading(heading, level=1)

            paragraph = doc.add_paragraph(
                str(payload[key])
            )
            normalize_paragraph(paragraph)

    list_sections = (
        ("Ожидаемые результаты", "learning_outcomes"),
        ("Необходимые инструменты", "required_tools"),
        ("Техника безопасности", "safety_notes"),
        ("Пошаговая инструкция", "task_steps"),
        ("Индивидуальные варианты", "individual_variants"),
        ("Контрольные вопросы", "control_questions"),
        ("Рефлексия", "reflection"),
    )

    for heading, key in list_sections:
        values = payload.get(key) or []

        if values:
            doc.add_heading(heading, level=1)

            for value in values:
                _add_list_item(doc, str(value))

    criteria = payload.get("evaluation_criteria") or []

    if criteria:
        doc.add_heading(
            "Критерии оценки",
            level=1,
        )

        for item in criteria:
            if isinstance(item, dict):
                _add_list_item(
                    doc,
                    f"{item.get('criterion', '')} — "
                    f"{item.get('weight', '')}",
                )
            else:
                _add_list_item(doc, str(item))

    time_allocation = payload.get(
        "time_allocation"
    ) or []

    if time_allocation:
        doc.add_heading(
            "Распределение времени — 70 минут",
            level=1,
        )

        for item in time_allocation:
            if isinstance(item, dict):
                _add_list_item(
                    doc,
                    f"{item.get('stage', '')}: "
                    f"{item.get('minutes', '')} мин.",
                )
            else:
                _add_list_item(doc, str(item))

    normalize_document_fonts(doc)

    file = BytesIO()
    doc.save(file)
    file.seek(0)

    return file