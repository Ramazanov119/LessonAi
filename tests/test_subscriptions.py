import csv
import io
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.subscription_service import SubscriptionService, remaining_days, subscriptions_csv
from services.supabase_service import SupabaseServiceError


def access(admin=False, allowed=True, user='teacher'):
    return dict(user_id=user, is_admin=admin, allowed=allowed, enforced=True,
                status='active' if allowed else 'expired', ends_at='2030-01-01T00:00:00+00:00',
                server_time='2029-12-01T00:00:00+00:00', reason='')


class SubscriptionTest(unittest.TestCase):
    def test_errors_and_malformed_results_fail_closed(self):
        for data in (None, [], {}, {'allowed': 'true'}, {**access(), 'is_admin': 'true'}, {**access(), 'user_id': None}):
            client = Mock()
            client.rpc.return_value.execute.return_value.data = data
            with self.assertRaises(SupabaseServiceError):
                SubscriptionService(client).require_access()
        client.rpc.return_value.execute.side_effect = RuntimeError('private secret')
        with self.assertRaises(SupabaseServiceError) as err:
            SubscriptionService(client).access()
        self.assertNotIn('private secret', str(err.exception))

    def test_status_not_cached_or_shared(self):
        first, second = Mock(), Mock()
        first.rpc.return_value.execute.return_value.data = access(user='first')
        second.rpc.return_value.execute.return_value.data = access(user='second', allowed=False)
        a, b = SubscriptionService(first), SubscriptionService(second)
        self.assertEqual(a.require_access()['user_id'], 'first')
        with self.assertRaises(SupabaseServiceError):
            b.require_access()
        first.rpc.return_value.execute.return_value.data = access(user='first', allowed=False)
        with self.assertRaises(SupabaseServiceError):
            a.require_access()

    def test_warning_thresholds_use_server_time(self):
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        for days in (7, 3, 1, 0, -1):
            status = {'ends_at': (now+timedelta(days=days)).isoformat(), 'server_time': now.isoformat()}
            self.assertEqual(remaining_days(status), days)

    def test_csv_is_excel_readable_and_does_not_execute_formulas(self):
        rows = [{'user_id':'1','full_name':'=HYPERLINK("bad")', 'email':'test@example.test', 'reason':'  +CMD'}]
        data = subscriptions_csv(rows)
        self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
        row = next(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
        self.assertTrue(row['full_name'].startswith("'="))
        self.assertTrue(row['reason'].startswith("'"))

    def test_app_navigation_permissions_and_expired_gate(self):
        from streamlit.testing.v1 import AppTest
        for admin, allowed in ((True,True),(False,True),(False,False)):
            with self.subTest(admin=admin, allowed=allowed):
                teacher = Mock()
                teacher.restore_session.return_value = SimpleNamespace(access_token='new-a', refresh_token='new-r')
                teacher.get_profile.return_value = SimpleNamespace(full_name='Teacher',college='ETEC')
                teacher.get_daily_count.return_value = 0
                teacher.list_lessons.return_value = []
                app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'))
                app.secrets.update({'OPENAI_API_KEY':'test','OPENROUTER_API_KEY':'test','SUPABASE_URL':'https://example.test','SUPABASE_ANON_KEY':'test'})
                app.session_state['auth_session'] = {'access_token':'old-a','refresh_token':'old-r'}
                with patch('services.supabase_service.create_supabase_client', return_value=Mock()), \
                     patch('services.supabase_service.SupabaseService', return_value=teacher), \
                     patch('services.subscription_service.SubscriptionService.access', return_value=access(admin,allowed)), \
                     patch('ui.release_notice.render_release_notice'):
                    app.run(timeout=15)
                self.assertFalse(app.exception, str(app.exception))
                navigation = next(r for r in app.radio if r.label=='Раздел')
                self.assertEqual('Админ-панель' in navigation.options, admin)
                if not allowed:
                    teacher.list_lessons.assert_not_called()
                    self.assertTrue(app.error)
                self.assertEqual(app.session_state['auth_session']['refresh_token'], 'new-r')

    def test_admin_ui_rechecks_role_before_loading_users(self):
        from streamlit.testing.v1 import AppTest
        source = '''
from unittest.mock import Mock
from ui.subscriptions import render_admin
service = Mock()
service.access.return_value = {'is_admin': False}
render_admin(service, {'user_id':'test'})
assert not service.users.called
'''
        app = AppTest.from_string(source).run(timeout=45)
        self.assertFalse(app.exception)
        self.assertTrue(app.error)

    def test_admin_form_requires_confirmation_and_prevents_self_suspension(self):
        from streamlit.testing.v1 import AppTest
        source = '''
import streamlit as st
from unittest.mock import Mock
from ui.subscriptions import render_admin
if 'service' not in st.session_state:
    svc = Mock()
    svc.access.return_value = {'is_admin':True}
    svc.users.return_value = [dict(user_id='admin',email='admin@example.test',full_name='Admin',college='ETEC',
        plan='standard',status='active',ends_at='2030-01-01T00:00:00+00:00',days_left=30,reason='',suspended=False)]
    svc.history.return_value = []
    st.session_state['service'] = svc
render_admin(st.session_state['service'], {'user_id':'admin'})
'''
        app = AppTest.from_string(source).run(timeout=45)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.metric), 5)
        next(b for b in app.button if b.label=='Применить').click().run(timeout=45)
        self.assertFalse(app.session_state['service'].change.called)
        self.assertTrue(app.warning)
        next(s for s in app.selectbox if s.label=='Действие').select('suspend')
        next(c for c in app.checkbox if 'изменение доступа' in c.label).check()
        next(b for b in app.button if b.label=='Применить').click().run(timeout=45)
        self.assertFalse(app.session_state['service'].change.called)
        self.assertTrue(app.error)
        self.assertFalse(app.exception)
