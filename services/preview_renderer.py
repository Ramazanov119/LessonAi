import base64
import html
import json
from contextlib import contextmanager

import streamlit as st

from config.colleges import get_college_config

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


def _lecture_body(data):
    blocks = []
    if data.get("relevance"):
        blocks += ["<h1>1. Актуальность</h1>", _paragraph(data["relevance"])]
    if data.get("learning_goals"):
        blocks += ["<h1>2. Цели обучения</h1>", _list(data["learning_goals"])]
    if data.get("key_terms"):
        blocks.append("<h1>3. Ключевые понятия</h1>")
        for item in data["key_terms"]:
            blocks.append(f"<h2>{_safe_text(item.get('term', 'Понятие'))}</h2>")
            blocks.append(_paragraph(item.get("definition", "")))
    if data.get("main_material"):
        blocks.append("<h1>4. Основной теоретический материал</h1>")
        for item in data["main_material"]:
            blocks.append(f"<h2>{_safe_text(item.get('title', 'Материал'))}</h2>")
            blocks.append(_paragraph(item.get("content", "")))
            if item.get("examples"):
                blocks.append("<h3>Примеры</h3>")
                blocks.append(_list(item["examples"]))
    if data.get("practice_examples"):
        blocks += ["<h1>5. Практические примеры</h1>", _list(data["practice_examples"])]
    case = data.get("case_study") or {}
    if case:
        blocks.append("<h1>6. Профессиональная ситуация / кейс</h1>")
        for title, key in (("Сценарий", "scenario"), ("Анализ", "analysis"), ("Решение", "solution")):
            if case.get(key):
                blocks.append(f"<h2>{title}</h2><div class='ai-edu-info'>{_paragraph(case[key])}</div>")
    if data.get("common_errors"):
        blocks.append("<h1>7. Типичные ошибки</h1>")
        for item in data["common_errors"]:
            blocks.append(f"<h2>{_safe_text(item.get('error', 'Ошибка'))}</h2>")
            blocks.append(_paragraph(item.get("fix", item.get("why", ""))))
    if data.get("summary"):
        blocks += ["<h1>8. Резюме</h1>", _list(data["summary"])]
    if data.get("review_questions"):
        blocks += ["<h1>9. Вопросы для закрепления</h1>", "<ol>" + "".join(f"<li>{_safe_text(item)}</li>" for item in data["review_questions"]) + "</ol>"]
    if data.get("preparation_for_practice"):
        blocks += ["<h1>10. Подготовка к практическому занятию</h1>", _paragraph(data["preparation_for_practice"])]
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
    logo = _logo_data(metadata.get("college"))
    logo_html = f"<img class='ai-edu-logo' src='{logo}' alt='Логотип колледжа'>" if logo else ""
    if document_type == "Лекция":
        body = _lecture_body(content)
    elif document_type == "Практическое занятие":
        body = _practice_body(content)
    else:
        body = _generic_body(content, document_type)
    if schema:
        body += f"<h2>Схема</h2>{_paragraph(schema)}"
    if visual:
        body += f"<h2>Иллюстрация</h2>{_paragraph(visual)}"
    html_content = f"""
    <div class='ai-edu-preview-wrap'>
      <div class='ai-edu-preview-label'>Предпросмотр документа</div>
      <div class='ai-edu-document'>
        <section class='ai-edu-page ai-edu-cover'>
          {logo_html}
          <p class='ai-edu-meta'><strong>Преподаватель:</strong> {_safe_text(metadata.get('teacher'))}</p>
          <p class='ai-edu-meta'><strong>Дата:</strong> {_safe_text(metadata.get('date'))}</p>
          <div class='ai-edu-cover-title'>{_safe_text(metadata.get('subject'))}</div>
          <div class='ai-edu-cover-type'>{_safe_text(document_type).upper()}</div>
          <div class='ai-edu-cover-topic'>{_safe_text(metadata.get('topic'))}</div>
        </section>
        <section class='ai-edu-page ai-edu-content'>{body}</section>
      </div>
    </div>
    """
    st.markdown(html_content, unsafe_allow_html=True)
