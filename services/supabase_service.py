from dataclasses import asdict
from datetime import date
from typing import Any, Optional
import uuid

from models.generation import LessonMetadata, TeacherProfile

DAILY_LESSON_LIMIT = 8
FIXED_LESSON_DURATION = "70 минут"
ALLOWED_COLLEGES = ("ETEC", "META", "ALT", "Q", "ATKK")
MATERIAL_TYPES = ("lesson_plan", "lecture", "practice", "presentation")


class SupabaseServiceError(RuntimeError):
    """Raised when Supabase cannot complete an application operation."""


class DatabaseCompatibilityError(SupabaseServiceError):
    """Storage cannot safely accept a generated lesson plan."""


DATABASE_UPDATE_MESSAGE = 'Требуется обновление базы данных LessonAI. Генерация временно недоступна.'


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

    def _profile_from_user(self, user: Any, *, fallback_email: str = "") -> TeacherProfile:
        metadata = getattr(user, "user_metadata", {}) or {}
        full_name = (
            metadata.get("full_name")
            or metadata.get("fullName")
            or metadata.get("name")
            or ""
        )
        if not full_name:
            email = getattr(user, "email", "") or fallback_email
            if email:
                full_name = email.split("@", 1)[0].strip() or "Преподаватель"
            else:
                full_name = "Преподаватель"

        college = metadata.get("college") or "ETEC"
        if college not in ALLOWED_COLLEGES:
            college = "ETEC"

        return TeacherProfile(full_name=full_name, college=college)

    def _ensure_profile_exists(self, user: Any, *, fallback_email: str = "") -> dict[str, Any]:
        if user is None or not getattr(user, "id", None):
            return {}

        profile = self._profile_from_user(user, fallback_email=fallback_email)
        try:
            existing = (
                self.client.table("profiles")
                .select("id")
                .eq("id", user.id)
                .limit(1)
                .execute()
            )
        except Exception as error:
            raise SupabaseServiceError(
                "Не удалось проверить наличие профиля преподавателя."
            ) from error

        if existing.data:
            return existing.data[0]

        return self._upsert_profile(profile, user.id)

    def sign_up(self, email: str, password: str, profile: TeacherProfile):
        if profile.college not in ALLOWED_COLLEGES:
            raise AuthenticationError("Выберите колледж")
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
                f"Не удалось зарегистрироваться. Проверьте email и пароль. {error}"
            ) from error
        if response.user is None:
            raise AuthenticationError("Supabase не вернул созданного пользователя.")

        if response.session is None:
            # Email confirmation может быть включён, и в этом случае пользователь уже создан,
            # но authenticated session не передаётся на этом шаге. В таком случае мы не
            # создаём профиль в обход существующего flow: профиль будет создан после входа.
            return response, None

        self._set_session(response.session)
        self._ensure_profile_exists(response.user, fallback_email=email)
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
        self._ensure_profile_exists(response.user, fallback_email=email)
        return response.session

    def restore_session(self, access_token: str, refresh_token: str):
        try:
            response = self.client.auth.set_session(access_token, refresh_token)
        except Exception as error:
            raise AuthenticationError("Сессия истекла. Войдите снова.") from error
        if response.user is None or response.session is None:
            raise AuthenticationError("Сессия недействительна. Войдите снова.")
        self._set_session(response.session)
        self._ensure_profile_exists(response.user)
        return response.session

    def sign_out(self):
        try:
            self.client.auth.sign_out()
        except Exception as error:
            raise AuthenticationError("Не удалось завершить сессию.") from error

    def get_account_preferences(self):
        """Authenticated user's metadata; never read another account or use admin APIs."""
        try:
            user = self.client.auth.get_user().user
            if user is None:
                raise ValueError('No authenticated user')
            return {'id': user.id, 'metadata': dict(user.user_metadata or {})}
        except Exception as error:
            raise SupabaseServiceError('Не удалось загрузить пользовательские настройки.') from error

    def mark_release_seen(self, release_id):
        from services.release_notice import SEEN_KEY
        account = self.get_account_preferences()
        previous = account['metadata'].get(SEEN_KEY, [])
        previous = previous if isinstance(previous, list) else []
        if release_id in previous:
            return False
        seen = list(dict.fromkeys([item for item in previous if isinstance(item, str)] + [release_id]))
        try:
            # Update only our metadata key. Auth merges top-level data keys;
            # profile, role, subscription, XP and language are never submitted.
            response = self.client.auth.update_user({'data': {SEEN_KEY: seen}})
            if response.user is None or release_id not in (response.user.user_metadata or {}).get(SEEN_KEY, []):
                raise ValueError('Update not confirmed')
        except Exception as error:
            raise SupabaseServiceError('Не удалось сохранить просмотр уведомления.') from error
        return True

    def get_profile(self) -> TeacherProfile:
        try:
            response = (
                self.client.table("profiles")
                .select("id, full_name, college")
                .single()
                .execute()
            )
        except Exception as error:
            raise SupabaseServiceError(
                "Не удалось загрузить профиль преподавателя."
            ) from error

        if not response.data:
            try:
                auth_user = self.client.auth.get_user().user
            except Exception:
                auth_user = None

            if auth_user is not None:
                self._ensure_profile_exists(auth_user)
                response = (
                    self.client.table("profiles")
                    .select("id, full_name, college")
                    .single()
                    .execute()
                )

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

    def ensure_lesson_plan_storage(self, *, operation_id=None):
        """Read-only RPC. Never probe readiness by attempting a document write."""
        operation_id = operation_id or str(uuid.uuid4())
        try:
            response = self.client.rpc('lesson_plan_storage_status', {}).execute()
        except Exception as error:
            from services.storage_diagnostics import database_failure
            details = database_failure(error, 'lesson_plan_storage_status', 'database_preflight', operation_id)
            if details['reason'] == 'auth_required' or details['code'] in ('PGRST301', 'PGRST302'):
                failed = AuthenticationError('Сессия истекла. Войдите снова.')
            elif details['code'] in ('PGRST202', 'PGRST203', '42883', '42501'):
                failed = DatabaseCompatibilityError(DATABASE_UPDATE_MESSAGE)
            else:
                failed = SupabaseServiceError('Не удалось проверить доступность базы данных. Генерация не запускалась.')
            failed.diagnostics = details
            raise failed from error
        data = response.data
        if not isinstance(data, dict) or data.get('api_version') != 2 or data.get('ready') is not True:
            failed = DatabaseCompatibilityError(DATABASE_UPDATE_MESSAGE)
            from services.storage_diagnostics import database_failure
            failed.diagnostics = database_failure(failed, 'lesson_plan_storage_status', 'database_preflight', operation_id,
                                                  data.get('reasons') if isinstance(data, dict) else None)
            raise failed
        return data

    def save_lesson_plan(self, lesson, content, *, existing_lesson_id=None, operation_id=None):
        """One transaction saves the plan and consumes quota only on success."""
        if lesson.college not in ALLOWED_COLLEGES:
            raise SupabaseServiceError("Недопустимое значение колледжа.")
        try:
            operation_id = str(uuid.UUID(str(operation_id))) if operation_id is not None else str(uuid.uuid4())
            existing_lesson_id = str(uuid.UUID(str(existing_lesson_id))) if existing_lesson_id is not None else None
        except ValueError as error:
            raise SupabaseServiceError('Некорректный идентификатор операции сохранения.') from error
        parameters = {
            "p_subject": lesson.subject, "p_topic": lesson.topic,
            "p_group_name": lesson.group_name, "p_course": lesson.course,
            "p_duration": FIXED_LESSON_DURATION,
            "p_lesson_date": lesson.lesson_date.isoformat(), "p_language": lesson.language,
            "p_lesson_type": lesson.lesson_type, "p_speciality": lesson.speciality,
            "p_chair": lesson.chair, "p_material_content": content,
            "p_existing_lesson_id": existing_lesson_id,
            "p_operation_id": operation_id,
        }
        try:
            response = self.client.rpc("save_lesson_plan_with_daily_limit", parameters).execute()
        except Exception as error:
            from services.storage_diagnostics import database_failure
            details = database_failure(error, 'save_lesson_plan_with_daily_limit', 'save', operation_id)
            if details['reason'] == 'daily_limit_reached':
                failed = DailyLimitExceeded(f"Достигнут дневной лимит: {DAILY_LESSON_LIMIT} занятий.")
            elif details['code'] in ('PGRST202', 'PGRST203', '42883', '42501'):
                failed = DatabaseCompatibilityError(DATABASE_UPDATE_MESSAGE)
            elif details['reason'] == 'idempotency_conflict':
                failed = SupabaseServiceError('Содержимое операции изменилось. Создайте отдельную операцию сохранения.')
            elif details['reason'] in ('auth_required', 'authentication_failed'):
                failed = AuthenticationError('Сессия истекла. Войдите снова.')
            elif details['reason'] == 'lesson_not_found':
                failed = SupabaseServiceError('Занятие недоступно для сохранения.')
            else:
                failed = SupabaseServiceError('Не удалось сохранить готовый план. Материал сохранён в текущей сессии; повторите сохранение после устранения проблемы.')
            failed.diagnostics = details
            raise failed from error
        if not response.data:
            raise SupabaseServiceError("Supabase не подтвердил сохранение готового плана.")
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
        payload = {
            "id": user_id,
            "full_name": profile.full_name.strip() or "Преподаватель",
            "college": profile.college if profile.college in ALLOWED_COLLEGES else "college",
            "role": "teacher",
            "subscription_status": "pending",
            "subscription_plan": "standard",
        }
        try:
            response = (
                self.client.table("profiles")
                .upsert(payload, on_conflict="id")
                .execute()
            )
            if not response.data:
                raise SupabaseServiceError("Supabase не подтвердил сохранение профиля.")
            return response.data[0] if isinstance(response.data, list) else response.data
        except Exception as error:
            raise SupabaseServiceError(
                "Пользователь создан, но профиль сохранить не удалось."
            ) from error

    def _set_session(self, session):
        self.client.auth.set_session(session.access_token, session.refresh_token)
