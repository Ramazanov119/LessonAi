from dataclasses import asdict
from datetime import date
from typing import Any, Optional

from models.generation import LessonMetadata, TeacherProfile

DAILY_LESSON_LIMIT = 8
FIXED_LESSON_DURATION = "70 минут"
ALLOWED_COLLEGES = ("ETEC", "META")
MATERIAL_TYPES = ("lesson_plan", "lecture", "practice", "presentation")


class SupabaseServiceError(RuntimeError):
    """Raised when Supabase cannot complete an application operation."""


class DailyLimitExceeded(SupabaseServiceError):
    """Raised when the authenticated teacher reached the daily lesson limit."""


class AuthenticationError(SupabaseServiceError):
    """Raised when authentication fails."""


def create_supabase_client(url: str, anon_key: str) -> Any:
    if not url or not anon_key:
        raise SupabaseServiceError(
            "Supabase не настроен: укажите SUPABASE_URL и SUPABASE_ANON_KEY."
        )
    try:
        from supabase import create_client

        return create_client(url, anon_key)
    except ImportError as error:
        raise SupabaseServiceError(
            "Не установлен Python-пакет supabase. Выполните pip install -r requirements.txt."
        ) from error
    except Exception as error:
        raise SupabaseServiceError(
            "Не удалось создать подключение к Supabase. Проверьте настройки."
        ) from error


class SupabaseService:
    def __init__(self, client: Any):
        self.client = client

    def sign_up(self, email: str, password: str, profile: TeacherProfile):
        if profile.college not in ALLOWED_COLLEGES:
            raise AuthenticationError("Выберите колледж ETEC или META.")
        try:
            response = self.client.auth.sign_up(
                {
                    "email": email,
                    "password": password,
                    "options": {"data": asdict(profile)},
                }
            )
        except Exception as error:
            raise AuthenticationError(
                "Не удалось зарегистрироваться. Проверьте email и пароль."
            ) from error
        if response.user is None:
            raise AuthenticationError("Supabase не вернул созданного пользователя.")
        if response.session is None:
            return response, None
        self._set_session(response.session)
        self._upsert_profile(profile, response.user.id)
        return response, response.session

    def sign_in(self, email: str, password: str):
        try:
            response = self.client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except Exception as error:
            raise AuthenticationError(
                "Не удалось войти. Проверьте email и пароль."
            ) from error
        if response.user is None or response.session is None:
            raise AuthenticationError("Supabase не вернул активную сессию.")
        self._set_session(response.session)
        return response.session

    def restore_session(self, access_token: str, refresh_token: str):
        try:
            response = self.client.auth.set_session(access_token, refresh_token)
        except Exception as error:
            raise AuthenticationError("Сессия истекла. Войдите снова.") from error
        if response.user is None or response.session is None:
            raise AuthenticationError("Сессия недействительна. Войдите снова.")
        return response.session

    def sign_out(self):
        try:
            self.client.auth.sign_out()
        except Exception as error:
            raise AuthenticationError("Не удалось завершить сессию.") from error

    def get_profile(self) -> TeacherProfile:
        try:
            response = self.client.table("profiles").select("id, full_name, college").single().execute()
        except Exception as error:
            raise SupabaseServiceError(
                "Не удалось загрузить профиль преподавателя."
            ) from error
        if not response.data:
            raise SupabaseServiceError("Профиль преподавателя не найден.")
        college = response.data.get("college")
        if college not in ALLOWED_COLLEGES:
            raise SupabaseServiceError("В профиле указано недопустимое значение колледжа.")
        return TeacherProfile(
            full_name=response.data.get("full_name", ""),
            college=college,
        )

    def get_daily_count(self, on_date: Optional[date] = None) -> int:
        params = {}
        if on_date is not None:
            params["p_lesson_date"] = on_date.isoformat()
        query = self.client.rpc(
            "get_daily_lesson_count",
            params,
        )
        try:
            response = query.execute()
        except Exception as error:
            raise SupabaseServiceError(
                "Не удалось получить дневной лимит."
            ) from error
        return int(response.data or 0)

    def create_lesson(self, lesson: LessonMetadata) -> dict[str, Any]:
        if lesson.college not in ALLOWED_COLLEGES:
            raise SupabaseServiceError("Недопустимое значение колледжа.")
        try:
            response = self.client.rpc(
                "create_lesson_with_daily_limit",
                {
                    "p_subject": lesson.subject,
                    "p_topic": lesson.topic,
                    "p_group_name": lesson.group_name,
                    "p_course": lesson.course,
                    "p_duration": FIXED_LESSON_DURATION,
                    "p_lesson_date": lesson.lesson_date.isoformat(),
                    "p_language": lesson.language,
                    "p_lesson_type": lesson.lesson_type,
                    "p_speciality": lesson.speciality,
                    "p_chair": lesson.chair,
                },
            ).execute()
        except Exception as error:
            message = str(error)
            if "DAILY_LIMIT_REACHED" in message:
                raise DailyLimitExceeded(
                    f"Достигнут дневной лимит: {DAILY_LESSON_LIMIT} занятий."
                ) from error
            raise SupabaseServiceError(
                "Не удалось сохранить занятие в Supabase."
            ) from error
        if not response.data:
            raise SupabaseServiceError("Supabase не подтвердил создание занятия.")
        return response.data[0] if isinstance(response.data, list) else response.data

    def list_lessons(self) -> list[dict[str, Any]]:
        try:
            response = (
                self.client.table("lessons")
                .select(
                    "id, full_name, topic, subject, group_name, course, duration, "
                    "lesson_date, language, lesson_type, speciality, chair, college, "
                    "created_at"
                )
                .order("created_at", desc=True)
                .execute()
            )
        except Exception as error:
            raise SupabaseServiceError("Не удалось загрузить историю занятий.") from error
        return response.data or []

    def upsert_material(self, lesson_id: str, material_type: str, content: str) -> dict[str, Any]:
        if material_type not in MATERIAL_TYPES:
            raise SupabaseServiceError("Недопустимый тип материала.")
        try:
            response = self.client.table("lesson_materials").upsert(
                {
                    "lesson_id": lesson_id,
                    "material_type": material_type,
                    "content": content,
                },
                on_conflict="lesson_id,material_type",
            ).execute()
        except Exception as error:
            raise SupabaseServiceError("Не удалось сохранить материал занятия.") from error
        if not response.data:
            raise SupabaseServiceError("Supabase не подтвердил сохранение материала.")
        return response.data[0] if isinstance(response.data, list) else response.data

    def list_materials(self, lesson_id: str) -> list[dict[str, Any]]:
        try:
            response = (
                self.client.table("lesson_materials")
                .select("id, lesson_id, material_type, content, created_at, updated_at")
                .eq("lesson_id", lesson_id)
                .order("material_type")
                .execute()
            )
        except Exception as error:
            raise SupabaseServiceError("Не удалось загрузить материалы занятия.") from error
        return response.data or []

    def _upsert_profile(self, profile: TeacherProfile, user_id: str):
        try:
            self.client.table("profiles").upsert(
                {
                    "id": user_id,
                    "full_name": profile.full_name,
                    "college": profile.college,
                }
            ).execute()
        except Exception as error:
            raise SupabaseServiceError(
                "Пользователь создан, но профиль сохранить не удалось."
            ) from error

    def _set_session(self, session):
        self.client.auth.set_session(session.access_token, session.refresh_token)
