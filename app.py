import html
import json
import logging

import streamlit as st
from datetime import date

from models import AIConfig, LessonMetadata, TeacherProfile
from services.ai import (
    AIServiceError,
    create_control,
    create_lesson,
    create_lecture,
    create_schema,
    create_visual,
    rework_lecture,
)
from services.docx_generator import build_doc, build_lecture_docx
from services.preview_renderer import generation_status, render_document_preview
from services.supabase_service import (
    ALLOWED_COLLEGES,
    DAILY_LESSON_LIMIT,
    AuthenticationError,
    DailyLimitExceeded,
    FIXED_LESSON_DURATION,
    SupabaseService,
    SupabaseServiceError,
    create_supabase_client,
)
from ui.theme import apply_theme

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

st.set_page_config(page_title="AI College Constructor", layout="wide")
apply_theme()

OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
OPENROUTER_API_KEY = st.secrets["OPENROUTER_API_KEY"]
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = st.secrets.get("SUPABASE_ANON_KEY", "")

AI_CONFIG = AIConfig(
    openai_api_key=OPENAI_API_KEY,
    openrouter_api_key=OPENROUTER_API_KEY,
)

SPECIALTIES = [
    "04130100-Менеджмент (қолдану салалары бойынша)/(по отраслям и по областям)",
    "04110100-Есеп және аудит/Учет и аудит",
    "04210100-Құқықтану/Правоведение",
    "06120100-Есептеу техникасы және ақпараттық желілер/Вычислительная техника и информационные сети",
    "10410300-Автомобиль көлігінде тасымалдауды ұйымдастыру және қозғалысты басқару/Организация перевозок и управление движением на автомобильном транспорте",
    "06130100-Бағдарламалық қызмет ету (түрлері бойынша)/Программное обеспечение (по видам)",
    "07130700-Электромеханикалық жабдықтарға техникалық қызмет көрсету, жөндеу және пайдалану",
    "07161300-Автомобиль көлігіне техникалық қызмет көрсету және пайдалану",
]

PCK_HEADS = ["Мавияева М.Д.", "Утегенова А.А.", "Серік А.М."]

LESSON_TYPES = [
    "Жаңа сабақ",
    "Аралас сабақ",
    "Практикалық сабақ",
    "Зертханалық сабақ",
    "Қайталау сабағы",
    "Бекіту сабағы",
]


def _store_session(session):
    st.session_state["auth_session"] = {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
    }


def _render_auth_screen(service):
    _render_brand_header()
    login_tab, registration_tab = st.tabs(["Войти", "Зарегистрироваться"])

    with login_tab:
        login_email = st.text_input("Email", key="login_email")
        login_password = st.text_input(
            "Пароль", type="password", key="login_password"
        )
        if st.button("Войти", key="login_button", type="primary"):
            try:
                _store_session(service.sign_in(login_email, login_password))
                st.rerun()
            except AuthenticationError as error:
                st.error(str(error))

    with registration_tab:
        registration_email = st.text_input("Email", key="registration_email")
        registration_password = st.text_input(
            "Пароль", type="password", key="registration_password"
        )
        registration_name = st.text_input("ФИО преподавателя")
        registration_college = st.radio(
            "Колледж",
            ALLOWED_COLLEGES,
            horizontal=True,
            key="registration_college",
        )
        college_logo_left, college_logo_right = st.columns(2)
        college_logo_left.image("assets/logos/etec.png", width=120)
        college_logo_right.image("assets/logos/meta.png", width=120)
        if st.button("Зарегистрироваться", key="registration_button", type="primary"):
            if not registration_name.strip():
                st.error("Укажите ФИО преподавателя.")
            else:
                try:
                    _, session = service.sign_up(
                        registration_email,
                        registration_password,
                        TeacherProfile(
                            registration_name.strip(), registration_college
                        ),
                    )
                    if session is None:
                        st.success("Регистрация завершена. Подтвердите email и войдите.")
                    else:
                        _store_session(session)
                        st.rerun()
                except (AuthenticationError, SupabaseServiceError) as error:
                    st.error(str(error))


def _preview_metadata(teacher_profile, subject, topic, lesson_date):
    return {
        "college": teacher_profile.college,
        "teacher": teacher_profile.full_name,
        "subject": subject.strip(),
        "topic": topic.strip(),
        "date": lesson_date.strftime("%d.%m.%Y"),
    }


def _show_generation_error():
    st.error("Не удалось создать материал. Попробуйте ещё раз.")


def _log_create_event(material_type, event, subject, topic):
    logger.info(
        "[CREATE] %s material_type=%s subject=%r topic=%r",
        event,
        material_type,
        subject.strip(),
        topic.strip(),
    )


def _log_create_failure(material_type, stage, subject, topic, error):
    logger.exception(
        "[CREATE] failed material_type=%s subject=%r topic=%r stage=%s "
        "exception_type=%s",
        material_type,
        subject.strip(),
        topic.strip(),
        stage,
        type(error).__name__,
    )

def _render_brand_header(*, daily_count=None):
    quota_class = ""
    if daily_count == DAILY_LESSON_LIMIT:
        quota_class = "danger"
    elif daily_count is not None and daily_count >= 6:
        quota_class = "warning"
    quota = ""
    if daily_count is not None:
        quota = (
            f"<span class='ai-edu-quota {quota_class}'>Сегодня "
            f"<strong>{daily_count}/{DAILY_LESSON_LIMIT}</strong></span>"
        )
    st.markdown(
        f"<div class='ai-edu-brand'><div class='ai-edu-wordmark'>"
        f"<span>AI</span> EDU</div>{quota}</div>"
        "<div class='ai-edu-brand-line'></div>",
        unsafe_allow_html=True,
    )


MATERIAL_LABELS = {
    "lesson_plan": ("📋", "Поурочный план"),
    "lecture": ("📚", "Лекция"),
    "practice": ("🛠", "Практическое занятие"),
    "presentation": ("🎨", "Презентация"),
}

WORKSPACE_VIEWS = ["Главная", "Мои занятия", "Создать занятие"]


def _sync_current_page(workspace_view_key):
    """Keep navigation state in sync with the workspace selector callback."""
    st.session_state["current_page"] = st.session_state[workspace_view_key]


def _go_to_create_lesson():
    """Navigate from the home CTA before widgets are built on the next rerun."""
    st.session_state["current_page"] = "Создать занятие"


def _render_lesson_card(lesson, materials):
    material_types = {item["material_type"] for item in materials}
    completed = len(material_types.intersection(MATERIAL_LABELS))
    title = html.escape(str(lesson.get("topic", "Без темы")))
    subject = html.escape(str(lesson.get("subject", "")))
    metadata = " · ".join(
        html.escape(str(lesson.get(key, "")))
        for key in ("group_name", "lesson_date", "duration")
    )
    st.markdown(
        f"<div class='ai-edu-lesson-card'><h3>{title}</h3>"
        f"<p class='ai-edu-card-subtitle'>{subject}</p>"
        f"<p class='ai-edu-card-meta'>{metadata}</p>"
        f"<p class='ai-edu-card-kit'>Комплект: <strong>{completed}/4</strong></p></div>",
        unsafe_allow_html=True,
    )
    for material_type, (_, label) in MATERIAL_LABELS.items():
        marker = "✓" if material_type in material_types else "○"
        st.caption(f"{marker} {label}")
    return st.button(
        "Открыть занятие",
        key=f"open_lesson_{lesson['id']}",
        type="secondary",
    )


def _render_lesson_workspace(service, lessons):
    st.subheader("Мои занятия")
    search = st.text_input("Поиск по теме, предмету или группе", placeholder="Например: сети")
    period = st.radio("Период", ["Все", "Сегодня", "Эта неделя"], horizontal=True)
    today = date.today()
    filtered = []
    for lesson in lessons:
        haystack = " ".join(
            str(lesson.get(key, "")).lower()
            for key in ("topic", "subject", "group_name")
        )
        if search.strip().lower() not in haystack:
            continue
        lesson_date = str(lesson.get("lesson_date", ""))
        if period == "Сегодня" and lesson_date != today.isoformat():
            continue
        if period == "Эта неделя":
            try:
                if date.fromisoformat(lesson_date).isocalendar()[:2] != today.isocalendar()[:2]:
                    continue
            except ValueError:
                continue
        filtered.append(lesson)

    if not filtered:
        st.info("Занятий пока нет. Создайте первое занятие, чтобы собрать материалы в одном месте.")
        return

    cards = st.columns(2, gap="large")
    for index, lesson in enumerate(filtered):
        with cards[index % 2]:
            try:
                materials = service.list_materials(lesson["id"])
            except SupabaseServiceError:
                materials = []
            if _render_lesson_card(lesson, materials):
                st.session_state["selected_lesson_id"] = lesson["id"]
                st.rerun()

    selected_id = st.session_state.get("selected_lesson_id")
    selected = next((lesson for lesson in lessons if lesson.get("id") == selected_id), None)
    if selected:
        st.divider()
        st.subheader(html.escape(str(selected.get("topic", "Занятие"))))
        st.caption(
            f"{selected.get('subject', '')} · {selected.get('group_name', '')} · "
            f"{selected.get('lesson_date', '')} · {selected.get('duration', FIXED_LESSON_DURATION)}"
        )
        materials = service.list_materials(selected["id"])
        material_map = {item["material_type"]: item for item in materials}
        detail_columns = st.columns(2, gap="medium")
        for index, (material_type, (_, label)) in enumerate(MATERIAL_LABELS.items()):
            with detail_columns[index % 2]:
                state = "Создан" if material_type in material_map else "Не создан"
                st.markdown(f"**{label}**  \n{state}")


def _material_content(content):
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


SUPABASE_SERVICE = None
if SUPABASE_URL and SUPABASE_ANON_KEY:
    try:
        SUPABASE_SERVICE = SupabaseService(
            create_supabase_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        )
    except SupabaseServiceError as error:
        st.error(str(error))
        st.stop()

if SUPABASE_SERVICE is None:
    st.error(
        "Supabase не настроен. Добавьте SUPABASE_URL и SUPABASE_ANON_KEY "
        "в Streamlit secrets."
    )
    st.stop()

auth_session = st.session_state.get("auth_session")
if auth_session:
    try:
        SUPABASE_SERVICE.restore_session(
            auth_session["access_token"], auth_session["refresh_token"]
        )
    except AuthenticationError:
        st.session_state.pop("auth_session", None)
        auth_session = None

if not auth_session:
    _render_auth_screen(SUPABASE_SERVICE)
    st.stop()

try:
    teacher_profile = SUPABASE_SERVICE.get_profile()
    daily_count = SUPABASE_SERVICE.get_daily_count()
except SupabaseServiceError as error:
    st.error(str(error))
    st.stop()

_render_brand_header(daily_count=daily_count)
header_name, header_college, header_logout = st.columns([2, 2, 1])
header_name.caption(f"Преподаватель · {teacher_profile.full_name}")
header_college.caption(f"Колледж · {teacher_profile.college}")
if header_logout.button("Выйти", type="tertiary"):
    try:
        SUPABASE_SERVICE.sign_out()
    finally:
        st.session_state.pop("auth_session", None)
        st.rerun()

try:
    lessons = SUPABASE_SERVICE.list_lessons()
except SupabaseServiceError as error:
    lessons = []
    st.error(str(error))

if "current_page" not in st.session_state:
    st.session_state["current_page"] = "Главная"

current_page = st.session_state["current_page"]
workspace_view_key = f"workspace_view_{current_page}"
st.radio(
    "Раздел",
    WORKSPACE_VIEWS,
    index=WORKSPACE_VIEWS.index(current_page),
    horizontal=True,
    key=workspace_view_key,
    on_change=_sync_current_page,
    args=(workspace_view_key,),
)
if current_page in ("Главная", "Мои занятия"):
    st.markdown(
        f"<div class='ai-edu-panel'><h2>Добро пожаловать, "
        f"{html.escape(teacher_profile.full_name)}</h2>"
        f"<p>Рабочее пространство преподавателя · {html.escape(teacher_profile.college)}</p></div>",
        unsafe_allow_html=True,
    )
    _render_lesson_workspace(SUPABASE_SERVICE, lessons)
    if current_page == "Главная":
        st.button(
            "+ Создать занятие",
            type="primary",
            on_click=_go_to_create_lesson,
        )
    st.stop()

mode = st.radio(
    "Материал",
    ["Поурочный план", "Лекция", "Практическое занятие", "Презентация"],
    horizontal=True,
)
form_left, form_right = st.columns(2, gap="large")
with form_left:
    teacher_name = st.text_input(
        "ФИО преподавателя", value=teacher_profile.full_name, disabled=True
    )
    topic = st.text_input("Тема")
    course = st.selectbox("Курс", [1, 2, 3, 4])
    language = st.selectbox("Язык", ["Русский", "Қазақша"])
with form_right:
    subject = st.text_input("Предмет")
    group_name = st.text_input("Группа")
    lesson_date = st.date_input("Дата урока", value=date.today())
    specialty = st.selectbox("Специальность", SPECIALTIES)
pck = st.selectbox("Председатель ПЦК", PCK_HEADS)

if mode == "Поурочный план":
    lesson_type = st.selectbox("Тип урока", LESSON_TYPES)
    if st.button("Создать план урока", type="primary", icon="✨"):
        required_fields = {
            "ФИО преподавателя": teacher_name,
            "Предмет": subject,
            "Тема": topic,
            "Группа": group_name,
        }
        missing_fields = [
            name for name, value in required_fields.items() if not value.strip()
        ]
        if missing_fields:
            st.error("Заполните поля: " + ", ".join(missing_fields) + ".")
        elif daily_count >= DAILY_LESSON_LIMIT:
            st.error(f"Достигнут дневной лимит: {DAILY_LESSON_LIMIT} занятий.")
        else:
            material_type = "lesson_plan"
            stage = "start"
            _log_create_event(material_type, "start", subject, topic)
            try:
                with generation_status(
                    "Создаём поурочный план",
                    ["✓ Поурочный план готов"],
                ) as progress:
                    stage = "AI generation"
                    _log_create_event(material_type, "AI generation started", subject, topic)
                    progress.write("🧠 Анализируем тему урока...")
                    lesson = create_lesson(
                        subject, topic, language, specialty, pck, lesson_type, AI_CONFIG
                    )
                    _log_create_event(material_type, "AI generation completed", subject, topic)
                    progress.write("🎯 Формируем цели обучения...")
                    progress.write("⏱️ Распределяем этапы занятия...")
                    stage = "lesson creation"
                    _log_create_event(material_type, "lesson creation started", subject, topic)
                    saved_lesson = SUPABASE_SERVICE.create_lesson(
                        LessonMetadata(
                            full_name=teacher_profile.full_name,
                            college=teacher_profile.college,
                            subject=subject.strip(),
                            topic=topic.strip(),
                            group_name=group_name.strip(),
                            course=course,
                            duration=FIXED_LESSON_DURATION,
                            lesson_date=lesson_date,
                            language=language,
                            lesson_type=lesson_type,
                            speciality=specialty,
                            chair=pck,
                        )
                    )
                    _log_create_event(material_type, "lesson created", subject, topic)
                    stage = "material save"
                    _log_create_event(material_type, "material save started", subject, topic)
                    SUPABASE_SERVICE.upsert_material(
                        saved_lesson["lesson_id"], "lesson_plan", _material_content(lesson)
                    )
                    _log_create_event(material_type, "material saved", subject, topic)
                    daily_count = saved_lesson.get("daily_count", daily_count + 1)
                    progress.write("📝 Формируем поурочный план...")
                    lesson_fields = {
                        "topic": topic.strip(),
                        "subject": subject.strip(),
                        "teacher": teacher_profile.full_name,
                        "date": lesson_date.strftime("%d.%m.%Y"),
                        "course": course,
                        "group": group_name.strip(),
                        "lesson_type": lesson_type,
                    }
                    stage = "document generation"
                    _log_create_event(material_type, "document generation started", subject, topic)
                    progress.write("📄 Подготавливаем документ...")
                    doc = build_doc("План урока", lesson, fields=lesson_fields)
                    _log_create_event(material_type, "document generation completed", subject, topic)
                stage = "preview"
                _log_create_event(material_type, "preview started", subject, topic)
                render_document_preview(
                    lesson,
                    "План урока",
                    _preview_metadata(teacher_profile, subject, topic, lesson_date),
                )
                st.download_button("Скачать DOCX", doc, "lesson.docx", type="secondary")
                _log_create_event(material_type, "completed", subject, topic)
            except DailyLimitExceeded as error:
                _log_create_failure(material_type, stage, subject, topic, error)
                st.error(str(error))
            except Exception as error:
                _log_create_failure(material_type, stage, subject, topic, error)
                _show_generation_error()
elif mode == "Лекция":
    lecture_type = st.selectbox("Тип лекции", ["Лекция", "Обзорная лекция", "Профессиональная лекция"])
    if st.button("Создать лекцию", type="primary", icon="✨"):
        required_fields = {
            "ФИО преподавателя": teacher_name,
            "Предмет": subject,
            "Тема": topic,
            "Группа": group_name,
        }
        missing_fields = [
            name for name, value in required_fields.items() if not value.strip()
        ]
        if missing_fields:
            st.error("Заполните поля: " + ", ".join(missing_fields) + ".")
        else:
            material_type = "lecture"
            stage = "start"
            _log_create_event(material_type, "start", subject, topic)
            try:
                with generation_status(
                    "Создаём лекцию",
                    ["✓ Материал готов"],
                ) as progress:
                    stage = "AI generation"
                    _log_create_event(material_type, "AI generation started", subject, topic)
                    progress.write("🧠 Анализируем тему занятия...")
                    lecture = create_lecture(
                        subject, topic, language, specialty, pck, lecture_type, AI_CONFIG
                    )
                    _log_create_event(material_type, "AI generation completed", subject, topic)
                    stage = "lesson creation"
                    _log_create_event(material_type, "lesson creation started", subject, topic)
                    saved_lesson = SUPABASE_SERVICE.create_lesson(
                        LessonMetadata(
                            full_name=teacher_profile.full_name,
                            college=teacher_profile.college,
                            subject=subject.strip(),
                            topic=topic.strip(),
                            group_name=group_name.strip(),
                            course=course,
                            duration=FIXED_LESSON_DURATION,
                            lesson_date=lesson_date,
                            language=language,
                            lesson_type=lecture_type,
                            speciality=specialty,
                            chair=pck,
                        )
                    )
                    _log_create_event(material_type, "lesson created", subject, topic)
                    st.session_state["selected_lesson_id"] = saved_lesson["lesson_id"]
                    stage = "material save"
                    _log_create_event(material_type, "material save started", subject, topic)
                    SUPABASE_SERVICE.upsert_material(
                        saved_lesson["lesson_id"], "lecture", _material_content(lecture)
                    )
                    _log_create_event(material_type, "material saved", subject, topic)
                    progress.write("📚 Формируем структуру лекции...")
                    progress.write("✍️ Подготавливаем теоретический материал...")
                    progress.write("💡 Добавляем профессиональные примеры...")
                    st.session_state["lecture_text"] = lecture
                    stage = "document generation"
                    _log_create_event(material_type, "document generation started", subject, topic)
                    progress.write("📄 Формируем учебный документ...")
                    st.session_state["lecture_doc"] = build_lecture_docx(
                        lecture,
                        title=f"Лекция: {topic.strip()}",
                        college=teacher_profile.college,
                        subject=subject.strip(),
                        teacher=teacher_profile.full_name,
                        group=group_name.strip(),
                        course=course,
                        lesson_date=lesson_date,
                    )
                    _log_create_event(material_type, "document generation completed", subject, topic)
                    progress.write("✨ Завершаем оформление...")
            except Exception as error:
                _log_create_failure(material_type, stage, subject, topic, error)
                _show_generation_error()

    if "lecture_text" in st.session_state and "lecture_doc" in st.session_state:
        material_type = "lecture"
        stage = "preview"
        try:
            _log_create_event(material_type, "preview started", subject, topic)
            render_document_preview(
                st.session_state["lecture_text"],
                "Лекция",
                _preview_metadata(teacher_profile, subject, topic, lesson_date),
            )
            st.download_button(
                "Скачать DOCX",
                st.session_state["lecture_doc"],
                "lecture.docx",
                type="secondary",
            )
            _log_create_event(material_type, "completed", subject, topic)
        except Exception as error:
            _log_create_failure(material_type, stage, subject, topic, error)
            _show_generation_error()
        rework_mode = st.selectbox(
            "🔄 Переработать лекцию",
            [
                "Сделать содержательнее",
                "Добавить профессиональные примеры",
                "Добавить реальные кейсы",
                "Упростить язык",
                "Сделать научнее",
                "Добавить таблицы",
                "Добавить практические примеры",
                "Переработать полностью",
            ],
            key="lecture_rework_mode",
        )
        if st.button(
            "Применить переработку",
            key="lecture_rework_button",
            type="secondary",
            icon="🔄",
        ):
            material_type = "lecture"
            stage = "start"
            _log_create_event(material_type, "start", subject, topic)
            try:
                with generation_status(
                    "Перерабатываем лекцию",
                    ["✓ Материал готов"],
                ) as progress:
                    stage = "AI generation"
                    _log_create_event(material_type, "AI generation started", subject, topic)
                    progress.write("🧠 Анализируем текущий материал...")
                    updated_lecture = rework_lecture(
                        st.session_state["lecture_text"],
                        rework_mode,
                        AI_CONFIG,
                    )
                    _log_create_event(material_type, "AI generation completed", subject, topic)
                    progress.write("✍️ Улучшаем содержание и примеры...")
                    st.session_state["lecture_text"] = updated_lecture
                    if st.session_state.get("selected_lesson_id"):
                        stage = "material save"
                        _log_create_event(material_type, "material save started", subject, topic)
                        SUPABASE_SERVICE.upsert_material(
                            st.session_state["selected_lesson_id"],
                            "lecture",
                            _material_content(updated_lecture),
                        )
                        _log_create_event(material_type, "material saved", subject, topic)
                    stage = "document generation"
                    _log_create_event(material_type, "document generation started", subject, topic)
                    progress.write("📄 Обновляем учебный документ...")
                    st.session_state["lecture_doc"] = build_lecture_docx(
                        updated_lecture,
                        title=f"Лекция: {topic.strip()}",
                        college=teacher_profile.college,
                        subject=subject.strip(),
                        teacher=teacher_profile.full_name,
                        group=group_name.strip(),
                        course=course,
                        lesson_date=lesson_date,
                    )
                    _log_create_event(material_type, "document generation completed", subject, topic)
                st.rerun()
            except Exception as error:
                _log_create_failure(material_type, stage, subject, topic, error)
                _show_generation_error()
else:
    st.info("Генератор практического занятия и презентации будет подключён к этому занятию без создания новой темы.")
