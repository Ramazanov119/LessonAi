"""Uncached access checks against the shared AiEdu profile and generation log."""
import logging
from datetime import datetime, timedelta, timezone

from services.supabase_service import SupabaseServiceError

logger = logging.getLogger(__name__)

ACCESS_DENIED = 'Доступ к платформе приостановлен или срок подписки истёк. Обратитесь к администратору.'


class PlatformAccess:
    def __init__(self, client):
        # The same anon-key client whose user session was restored by the app.
        self.client = client

    def profile(self):
        try:
            user_id = self.client.auth.get_user().user.id
            profile = self.client.table('profiles').select(
                'is_active, subscription_until, daily_limit, role, organization_id'
            ).eq('id', user_id).single().execute().data
            if not isinstance(profile, dict) or type(profile.get('is_active')) is not bool:
                raise ValueError('Invalid profile')
            active = profile['is_active']
            if profile.get('subscription_until') is not None:
                end = datetime.fromisoformat(profile['subscription_until'].replace('Z', '+00:00'))
                if end.tzinfo is None:
                    raise ValueError('Missing timezone')
                active = active and end >= datetime.now(timezone.utc)
            if profile.get('organization_id'):
                organization = self.client.table('organizations').select('is_active').eq(
                    'id', profile['organization_id']
                ).single().execute().data
                active = active and isinstance(organization, dict) and organization.get('is_active') is True
            limit = profile.get('daily_limit', 20)
            if type(limit) is not int or limit < 0:
                raise ValueError('Invalid daily limit')
            return {**profile, 'user_id': user_id, 'daily_limit': limit, 'allowed': active}
        except Exception as error:
            raise SupabaseServiceError('Не удалось проверить доступ к платформе. Обратитесь к администратору.') from error

    def daily_count(self, user_id):
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            result = self.client.table('generation_logs').select('id', count='exact', head=True).eq(
                'user_id', user_id
            ).gte('created_at', start.isoformat()).lt(
                'created_at', (start + timedelta(days=1)).isoformat()
            ).execute()
            if type(result.count) is not int or result.count < 0:
                raise ValueError('Missing count')
            return result.count
        except Exception as error:
            raise SupabaseServiceError('Не удалось проверить дневной лимит. Генерация не запускалась.') from error

    def record_success(self, user_id, *, agent_type=None, action_type=None,
                       model_name=None, duration_ms=0):
        if type(duration_ms) is not int or duration_ms < 0:
            raise ValueError('duration_ms must be a non-negative integer')
        payload = {
            'user_id': user_id,
            'agent_type': agent_type or 'lesson_plan',
            'action_type': action_type or 'generate',
            'status': 'success',
            'model_name': model_name or 'unknown',
            'duration_ms': duration_ms,
        }
        try:
            session = self.client.auth.get_session()
            if session is None or not session.access_token:
                raise ValueError('Нет активной пользовательской сессии Supabase. Войдите снова.')
            user = self.client.auth.get_user().user
            if user is None or str(user.id) != str(user_id):
                raise ValueError('user_id не совпадает с текущим пользователем Supabase.')
            # Explicitly use the current JWT for PostgREST, never the anon API key
            # as the Authorization bearer. get_session also refreshes expired JWTs.
            self.client.postgrest.auth(session.access_token)
            # No SELECT permission is needed just to acknowledge the INSERT.
            self.client.table('generation_logs').insert(payload, returning='minimal').execute()
        except Exception as error:
            logger.exception('generation_logs insert failed: user_id=%s agent_type=%s action_type=%s model_name=%s error=%s',
                             user_id, payload['agent_type'], payload['action_type'], payload['model_name'], error)
            raise SupabaseServiceError(
                f'Материал создан, но не удалось записать генерацию. Причина Supabase: {error}'
            ) from error
