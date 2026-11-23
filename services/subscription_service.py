"""Uncached, JWT-scoped subscription RPCs. Never uses a service-role client."""
import csv
import io
import math
from datetime import datetime

from services.supabase_service import SupabaseServiceError


class SubscriptionService:
    def __init__(self, client):
        self.client = client

    def _rpc(self, name, params=None):
        try:
            return self.client.rpc(name, params or {}).execute().data
        except Exception as error:
            raise SupabaseServiceError('Не удалось выполнить операцию подписки. Доступ не подтверждён; повторите попытку или обратитесь к администратору.') from error

    def access(self):
        result = self._rpc('subscription_access')
        if (not isinstance(result, dict) or type(result.get('allowed')) is not bool
                or type(result.get('is_admin')) is not bool or not result.get('user_id')
                or type(result.get('enforced')) is not bool):
            raise SupabaseServiceError('Не удалось подтвердить статус подписки.')
        try:
            if result.get('status') not in {'active', 'expired', 'suspended', 'missing', 'scheduled'}:
                raise ValueError('Unknown status')
            now = datetime.fromisoformat(result['server_time'].replace('Z', '+00:00'))
            if now.tzinfo is None:
                raise ValueError('Missing timezone')
            if result['enforced'] and result['allowed']:
                end = datetime.fromisoformat(result['ends_at'].replace('Z', '+00:00'))
                if result['status'] != 'active' or end <= now:
                    raise ValueError('Inconsistent access')
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise SupabaseServiceError('Не удалось подтвердить статус подписки.') from error
        return result

    def require_access(self):
        status = self.access()
        if not status['allowed']:
            raise SupabaseServiceError('Подписка неактивна. Обратитесь к администратору для оплаты или продления.')
        return status

    def users(self):
        return self._rpc('admin_subscription_users')

    def change(self, user_id, action, *, days=None, ends_at=None, reason='', plan='standard'):
        return self._rpc('admin_change_subscription', {
            'p_user_id': user_id, 'p_action': action, 'p_days': days,
            'p_ends_at': ends_at, 'p_reason': reason, 'p_plan': plan})

    def payment(self, user_id, amount, paid_at, method, comment):
        return self._rpc('admin_record_payment', {'p_user_id': user_id, 'p_amount_kzt': str(amount),
            'p_paid_at': paid_at, 'p_method': method, 'p_comment': comment})

    def history(self, user_id):
        return self._rpc('admin_subscription_history', {'p_user_id': user_id})


def remaining_days(status):
    """Use database time to avoid browser/server timezone disagreement."""
    if not status.get('ends_at'):
        return None
    end = datetime.fromisoformat(status['ends_at'].replace('Z', '+00:00'))
    now = datetime.fromisoformat(status['server_time'].replace('Z', '+00:00'))
    return math.ceil((end - now).total_seconds() / 86400)


def subscriptions_csv(rows):
    stream = io.StringIO()
    fields = ['user_id', 'email', 'full_name', 'college', 'plan', 'status', 'ends_at', 'days_left', 'reason']
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        # Spreadsheet formula injection: names, comments and email are untrusted.
        writer.writerow({key: ("'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else value)
                         for key, value in row.items()})
    return stream.getvalue().encode('utf-8-sig')
