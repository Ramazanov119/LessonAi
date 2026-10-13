import base64
import html
import json
from contextlib import contextmanager

import streamlit as st

from config.colleges import get_college_config
from services.lecture_localization import lecture_labels

@contextmanager
def generation_status(title, steps):
    """Show real generation stages without pretending to know a percentage."""
    with st.status(f"AI EDU · {title}", expanded=True) as status:
        status.write("Подготавливаем рабочий процесс...")
        try:
            yield status
        except Exception:
            status.update(label="Не удалось создать материал", state="error", expanded=False)
            raise
        status.update(label=steps[-1], state="complete", expanded=False)


def _safe_text(value):
    return html.escape(str(value or ""))


def _parse_content(content):
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return {"text": str(content or "")}
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(cleaned)
    except (TypeError, json.JSONDecodeError):
        return {"text": content}
    return parsed if isinstance(parsed, dict) else {"text": content}


def _logo_data(college):
    path = get_college_config(college)["logo"]
    if not path.exists():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _styles():
    st.markdown(
        """
        <style>
        .ai-edu-preview-wrap { background: #111318; padding: 1.25rem; border: 1px solid rgba(255,255,255,.12); border-radius: 10px; }
        .ai-edu-preview-label { margin: 0 0 .65rem; color: #b7bac3; font: 700 .78rem/1.2 sans-serif; letter-spacing: .08em; text-transform: uppercase; }
        .ai-edu-document { max-width: 820px; margin: 0 auto; color: #171717; font-family: "Times New Roman", Times, serif; }
        .ai-edu-page { background: #fff; border: 1px solid #d5d8dc; box-shadow: 0 5px 16px rgba(25, 31, 36, .12); padding: 2.3rem 3rem; }
        .ai-edu-page + .ai-edu-page { margin-top: 1.5rem; }
        .ai-edu-cover { min-height: 520px; }
        .ai-edu-logo { display: block; width: 5.6cm; max-width: 78%; height: auto; margin: 0 0 1rem; }
        .ai-edu-meta { margin: 0 0 .2rem; font-size: 1rem; line-height: 1.25; }
        .ai-edu-cover-title { margin: 4.2rem 0 .5rem; text-align: center; font-size: 1.35rem; font-weight: 700; }
        .ai-edu-cover-type, .ai-edu-cover-topic { margin: .45rem 0; text-align: center; font-size: 1.2rem; font-weight: 700; }
        .ai-edu-content { margin-top: 1.4rem; }
        .ai-edu-content h1, .ai-edu-content h2, .ai-edu-content h3 { margin: 1.05rem 0 .35rem; text-align: left; font-weight: 700; line-height: 1.2; }
        .ai-edu-content h1 { font-size: 1.12rem; }
        .ai-edu-content h2, .ai-edu-content h3 { font-size: 1rem; }
        .ai-edu-content p { margin: 0 0 .55rem; text-align: justify; font-size: 1rem; line-height: 1.28; text-indent: 1.25cm; }
        .ai-edu-content ul, .ai-edu-content ol { margin: .2rem 0 .7rem 1.35rem; padding-left: 1rem; font-size: 1rem; line-height: 1.35; }
        .ai-edu-content li { margin: .15rem 0; }
        .ai-edu-info { border-left: 3px solid #8b949e; margin: .8rem 0; padding: .35rem .8rem; }
        @media (max-width: 700px) { .ai-edu-preview-wrap { padding: .65rem; } .ai-edu-page { padding: 1.2rem 1rem; } .ai-edu-cover { min-height: 430px; } .ai-edu-cover-title { margin-top: 3rem; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _paragraph(text):
    return f"<p>{_safe_text(text)}</p>"


def _list(items):
    return "<ul>" + "".join(f"<li>{_safe_text(item)}</li>" for item in items) + "</ul>"


def _lecture_body(data, language="Русский"):
    labels = lecture_labels(language)
    blocks = []
    if data.get("relevance"):
        blocks += [f"<h1>1. {labels['relevance']}</h1>", _paragraph(data["relevance"])]
    if data.get("learning_goals"):
        blocks += [f"<h1>2. {labels['learning_goals']}</h1>", _list(data["learning_goals"])]
    if data.get("key_terms"):
        blocks.append(f"<h1>3. {labels['key_terms']}</h1>")
        for item in data["key_terms"]:
            blocks.append(f"<h2>{_safe_text(item.get('term', labels['term']))}</h2>")
            blocks.append(_paragraph(item.get("definition", "")))
    if data.get("main_material"):
        blocks.append(f"<h1>4. {labels['main_material']}</h1>")
        for item in data["main_material"]:
            blocks.append(f"<h2>{_safe_text(item.get('title', labels['material']))}</h2>")
            blocks.append(_paragraph(item.get("content", "")))
            if item.get("examples"):
                blocks.append(f"<h3>{labels['examples']}</h3>")
                blocks.append(_list(item["examples"]))
    if data.get("practice_examples"):
        blocks += [f"<h1>5. {labels['practice_examples']}</h1>", _list(data["practice_examples"])]
    case = data.get("case_study") or {}
    if case:
        blocks.append(f"<h1>6. {labels['case_study']}</h1>")
        for title, key in ((labels["scenario"], "scenario"), (labels["analysis"], "analysis"), (labels["solution"], "solution")):
            if case.get(key):
                blocks.append(f"<h2>{title}</h2><div class='ai-edu-info'>{_paragraph(case[key])}</div>")
    if data.get("common_errors"):
        blocks.append(f"<h1>7. {labels['common_errors']}</h1>")
        for item in data["common_errors"]:
            for key in ("error", "why", "fix"):
                if item.get(key):
                    blocks.append(f"<h2>{labels[key]}</h2>")
                    blocks.append(_paragraph(item[key]))
    if data.get("summary"):
        blocks += [f"<h1>8. {labels['summary']}</h1>", _list(data["summary"])]
    if data.get("review_questions"):
        blocks += [f"<h1>9. {labels['review_questions']}</h1>", "<ol>" + "".join(f"<li>{_safe_text(item)}</li>" for item in data["review_questions"]) + "</ol>"]
    if data.get("preparation_for_practice"):
        blocks += [f"<h1>10. {labels['preparation_for_practice']}</h1>", _paragraph(data["preparation_for_practice"])]
    if data.get("text"):
        blocks.append(_paragraph(data["text"]))
    return "".join(blocks)


def _practice_body(data):
    blocks = []
    text_sections = (
        ("Цель", "objective"),
        ("Краткая теория", "brief_theory"),
        ("Профессиональная ситуация", "professional_context"),
        ("Практическое задание", "main_task"),
        ("Ожидаемый результат", "expected_result"),
        ("Заключение", "conclusion"),
    )
    for heading, key in text_sections:
        if data.get(key):
            blocks += [f"<h1>{heading}</h1>", _paragraph(data[key])]

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
        if data.get(key):
            blocks += [f"<h1>{heading}</h1>", _list(data[key])]

    criteria = data.get("evaluation_criteria") or []
    if criteria:
        blocks.append("<h1>Критерии оценки</h1><ul>")
        for item in criteria:
            if isinstance(item, dict):
                blocks.append(f"<li>{_safe_text(item.get('criterion', ''))} — {_safe_text(item.get('weight', ''))}</li>")
            else:
                blocks.append(f"<li>{_safe_text(item)}</li>")
        blocks.append("</ul>")

    time_allocation = data.get("time_allocation") or []
    if time_allocation:
        blocks.append("<h1>Распределение времени — 70 минут</h1><ul>")
        for item in time_allocation:
            if isinstance(item, dict):
                blocks.append(f"<li>{_safe_text(item.get('stage', ''))}: {_safe_text(item.get('minutes', ''))} мин.</li>")
            else:
                blocks.append(f"<li>{_safe_text(item)}</li>")
        blocks.append("</ul>")
    return "".join(blocks)


def _meta_lesson_body(data, metadata):
    from services.lesson_validation import normalize_meta_lesson
    from services.meta_localization import meta_labels
    language = metadata.get("language", "Русский")
    data = normalize_meta_lesson(data, language=language,
                                 lesson_type=metadata.get("lesson_type", ""),
                                 lesson_date=metadata.get("date"))
    labels = meta_labels(language)
    blocks = [f"<h1>{labels['duration']}: {data['lesson_duration']} {labels['minute']}</h1>"]
    for title, key in ((labels['goal'], "goal"), (labels['results'], "results")):
        if data.get(key):
            blocks.extend((f"<h1>{title}</h1>", _paragraph(data[key])))
    for label, key in (("explanatory_method_label", "explanatory_illustrative_method"),
                       ("practical_task_label", "practical_task")):
        if data.get(key):
            blocks.extend((f"<h2>{labels[label]}:</h2>", _paragraph(data[key])))
    for stage in data["lesson_stages"]:
        blocks.append(f"<h2>{_safe_text(stage['name'])} ({stage['duration_minutes']} {labels['minute']})</h2>")
        blocks.append(_paragraph(stage["content"]))
    blocks.append("<table style='width:100%;table-layout:fixed;border-collapse:collapse'><thead><tr>")
    for heading in labels['headers']:
        blocks.append(f"<th style='border:1px solid #999;padding:5px;overflow-wrap:anywhere'>{heading}</th>")
    blocks.append("</tr></thead><tbody>")
    for item in data["assessment_items"]:
        descriptors = "<br>".join(f"{_safe_text(text)} — {points}" for text, points in
                                  zip(item["descriptors"], item["descriptor_points"]))
        values = (_safe_text(item["task_name"]), _safe_text(item["bloom_level"]),
                  _safe_text(item["assessment_criterion"]), descriptors, str(item["points"]))
        blocks.append("<tr>" + "".join(f"<td style='border:1px solid #999;padding:5px;overflow-wrap:anywhere'>{value}</td>" for value in values) + "</tr>")
    blocks.append(f"<tr><td colspan='4'>{labels['total']}</td><td>100</td></tr></tbody></table>")
    return "".join(blocks)


def _generic_body(data, document_type):
    blocks = [f"<h1>{_safe_text(document_type)}</h1>"]
    for key, value in data.items():
        if key == "text":
            blocks.append(_paragraph(value))
        elif isinstance(value, list):
            blocks += [f"<h2>{_safe_text(key.replace('_', ' ').title())}</h2>", _list(value)]
        elif isinstance(value, str) and value:
            blocks += [f"<h2>{_safe_text(key.replace('_', ' ').title())}</h2>", _paragraph(value)]
    return "".join(blocks)


def render_document_preview(content, document_type, metadata, *, schema=None, visual=None):
    """Render a reusable document-like preview for any generated material."""
    _styles()
    content = _parse_content(content)
    labels = lecture_labels(metadata.get("language"))
    is_lecture = document_type == "Лекция"
    teacher_label = labels["teacher"] if is_lecture else "Преподаватель"
    date_label = labels["date"] if is_lecture else "Дата"
    cover_type = labels["lecture"] if is_lecture else document_type
    logo = _logo_data(metadata.get("college"))
    logo_html = f"<img class='ai-edu-logo' src='{logo}' alt='{labels['logo']}'>" if logo else ""
    if document_type == "Лекция":
        body = _lecture_body(content, metadata.get("language"))
    elif document_type == "Практическое занятие":
        body = _practice_body(content)
    elif document_type in ("План урока", "Поурочный план") and str(metadata.get("college", "")).upper() == "META" and content.get("assessment_items"):
        body = _meta_lesson_body(content, metadata)
    else:
        body = _generic_body(content, document_type)
    if schema:
        body += f"<h2>{labels['schema'] if is_lecture else 'Схема'}</h2>{_paragraph(schema)}"
    if visual:
        body += f"<h2>{labels['visual'] if is_lecture else 'Иллюстрация'}</h2>{_paragraph(visual)}"
    html_content = f"""
    <div class='ai-edu-preview-wrap'>
      <div class='ai-edu-preview-label'>Предпросмотр документа</div>
      <div class='ai-edu-document'>
        <section class='ai-edu-page ai-edu-cover'>
          {logo_html}
          <p class='ai-edu-meta'><strong>{teacher_label}:</strong> {_safe_text(metadata.get('teacher'))}</p>
          <p class='ai-edu-meta'><strong>{date_label}:</strong> {_safe_text(metadata.get('date'))}</p>
          <div class='ai-edu-cover-title'>{_safe_text(metadata.get('subject'))}</div>
          <div class='ai-edu-cover-type'>{_safe_text(cover_type).upper()}</div>
          <div class='ai-edu-cover-topic'>{_safe_text(metadata.get('topic'))}</div>
        </section>
        <section class='ai-edu-page ai-edu-content'>{body}</section>
      </div>
    </div>
    """
    st.markdown(html_content, unsafe_allow_html=True)
