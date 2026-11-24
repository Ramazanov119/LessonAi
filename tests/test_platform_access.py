import ast
from pathlib import Path
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from services.platform_access import PlatformAccess
from services.supabase_service import SupabaseServiceError


class PlatformAccessTests(unittest.TestCase):
    def service(self, **overrides):
        client = Mock()
        client.auth.get_user.return_value.user.id = 'teacher-id'
        client.auth.get_session.return_value = SimpleNamespace(access_token='user-jwt', refresh_token='user-refresh')
        profile = dict(is_active=True, subscription_until=None, daily_limit_v1=20,
                       role='teacher', organization_id=None)
        profile.update(overrides)
        client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = profile
        return PlatformAccess(client), client

    def test_disabled_expired_and_unlimited_subscription(self):
        for changes, allowed in (({}, True), ({'is_active': False}, False),
                                 ({'subscription_until': (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()}, False),
                                 ({'subscription_until': (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}, True)):
            service, client = self.service(**changes)
            self.assertEqual(service.profile()['allowed'], allowed)
            client.table.return_value.select.return_value.eq.assert_called_with('id', 'teacher-id')

    def test_organization_and_missing_organization_deny_access(self):
        for organization in ({'is_active': False}, None, {'is_active': True}):
            service, client = self.service(organization_id='org')
            query = client.table.return_value.select.return_value.eq.return_value.single.return_value.execute
            profile = query.return_value.data
            query.side_effect = [SimpleNamespace(data=profile), SimpleNamespace(data=organization)]
            self.assertEqual(service.profile()['allowed'], organization == {'is_active': True})

    def test_invalid_limit_and_unavailable_profile_fail_closed(self):
        for limit in (True, '20', 1.5):
            service, _ = self.service(daily_limit_v1=limit)
            with self.assertRaises(SupabaseServiceError):
                service.profile()

    def test_personal_limit_fallback_and_closed_generation(self):
        for value, expected in ((7, 7), (None, 10), (0, 0), (-1, -1)):
            with self.subTest(value=value):
                service, client = self.service(daily_limit_v1=value, daily_limit=999)
                profile = service.profile()
                self.assertEqual(profile['daily_limit'], expected)
                self.assertEqual(profile['generation_allowed'], expected > 0)
                client.postgrest.auth.assert_called_once_with('user-jwt')
                client.table.return_value.select.assert_called_once_with(
                    'is_active, subscription_until, daily_limit_v1, role, organization_id')
        service, client = self.service()
        del client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data['daily_limit_v1']
        self.assertEqual(service.profile()['daily_limit'], 10)

    def test_profile_requires_authenticated_session(self):
        service, client = self.service()
        client.auth.get_session.return_value = None
        with self.assertRaises(SupabaseServiceError):
            service.profile()
        client.table.assert_not_called()

    def test_count_is_scoped_to_user_and_utc_day(self):
        service, client = self.service()
        query = client.table.return_value.select.return_value.eq.return_value.eq.return_value
        query.gte.return_value.lt.return_value.execute.return_value.count = 20
        self.assertEqual(service.daily_count('teacher-id'), 20)
        client.table.return_value.select.return_value.eq.assert_called_with('user_id', 'teacher-id')
        client.table.return_value.select.return_value.eq.return_value.eq.assert_called_once_with('status', 'success')
        self.assertTrue(query.gte.call_args.args[1].endswith('T00:00:00+00:00'))
        start = datetime.fromisoformat(query.gte.call_args.args[1])
        end = datetime.fromisoformat(query.gte.return_value.lt.call_args.args[1])
        self.assertEqual(end - start, timedelta(days=1))
        client.postgrest.auth.assert_called_once_with('user-jwt')
        service.record_success('teacher-id')
        client.table.return_value.insert.assert_called_once_with({
            'user_id': 'teacher-id', 'agent_type': 'lesson_plan', 'action_type': 'generate',
            'status': 'success', 'model_name': 'unknown', 'duration_ms': 0,
        }, returning='minimal')


    def test_authenticated_client_used_for_writing_log(self):
        service, client = self.service()
        service.record_success('teacher-id', agent_type='lecture', action_type='rework',
                               model_name='test-model', duration_ms=1250)
        client.postgrest.auth.assert_called_once_with('user-jwt')
        client.table.assert_called_once_with('generation_logs')
        client.table.return_value.insert.assert_called_once_with({
            'user_id': 'teacher-id', 'agent_type': 'lecture', 'action_type': 'rework',
            'status': 'success', 'model_name': 'test-model', 'duration_ms': 1250,
        }, returning='minimal')

    def test_missing_session_or_wrong_user_never_inserts(self):
        for missing_session in (True, False):
            service, client = self.service()
            if missing_session:
                client.auth.get_session.return_value = None
            else:
                client.auth.get_user.return_value.user.id = 'someone-else'
            with self.assertLogs('services.platform_access', level='ERROR'):
                with self.assertRaises(SupabaseServiceError):
                    service.record_success('teacher-id')
            client.table.return_value.insert.assert_not_called()
            client.postgrest.auth.assert_not_called()

    def test_invalid_duration_is_rejected_before_insert(self):
        for duration in (-1, 1.5, True, None):
            with self.subTest(duration=duration):
                service, client = self.service()
                with self.assertRaises(ValueError):
                    service.record_success('teacher-id', duration_ms=duration)
                client.table.return_value.insert.assert_not_called()

    def test_insert_failure_logs_exact_database_error(self):
        service, client = self.service()
        message = '23502: null value in column action_type violates not-null constraint'
        client.table.return_value.insert.return_value.execute.side_effect = RuntimeError(message)
        with self.assertLogs('services.platform_access', level='ERROR') as logs:
            with self.assertRaises(SupabaseServiceError) as raised:
                service.record_success('teacher-id')
        self.assertIn(message, '\n'.join(logs.output))
        self.assertIn(message, str(raised.exception))


class GenerationGuardTests(unittest.TestCase):
    def test_limit_failure_and_success(self):
        source = ast.parse((Path(__file__).resolve().parents[1] / 'app.py').read_text())
        guard = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == '_run_ai')
        class Stopped(BaseException):
            pass
        service, st = Mock(), Mock()
        st.stop.side_effect = Stopped
        service.profile.return_value = {'allowed': True, 'user_id': 'u', 'daily_limit': 20}
        namespace = dict(PLATFORM_ACCESS=service, st=st, ACCESS_DENIED='denied', SupabaseServiceError=SupabaseServiceError)
        exec(compile(ast.Module(body=[guard], type_ignores=[]), '<guard>', 'exec'), namespace)
        run = namespace['_run_ai']
        generator = Mock(return_value='material')
        service.daily_count.return_value = 20
        with self.assertRaises(Stopped):
            run(generator)
        generator.assert_not_called()
        st.warning.assert_called_once()
        st.warning.assert_called_with('Дневной лимит генераций (20 из 20) исчерпан. Обратитесь к администратору.')
        service.record_success.assert_not_called()
        for limit in (0, -1):
            service.profile.return_value['daily_limit'] = limit
            service.daily_count.return_value = 0
            with self.assertRaises(Stopped):
                run(generator)
            generator.assert_not_called()
        service.profile.return_value['daily_limit'] = 20
        service.daily_count.return_value = 19
        self.assertEqual(run(generator), 'material')
        service.record_success.assert_called_once_with('u')
        service.record_success.reset_mock()
        generator.side_effect = RuntimeError('provider failed')
        with self.assertRaises(RuntimeError):
            run(generator)
        service.record_success.assert_not_called()
        generator.side_effect = None
        service.record_success.side_effect = SupabaseServiceError('Supabase: RLS denied')
        self.assertEqual(run(generator), 'material')
        st.warning.assert_called_with('Supabase: RLS denied')
        service.profile.return_value['allowed'] = False
        with self.assertRaises(Stopped):
            run(generator)
        st.error.assert_called_with('denied')

    def test_creation_and_rework_buttons_disable_at_limit(self):
        source = ast.parse((Path(__file__).resolve().parents[1] / 'app.py').read_text())
        buttons = [node for node in ast.walk(source) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Attribute) and node.func.attr == 'button'
                   and node.args and isinstance(node.args[0], ast.Constant)
                   and node.args[0].value in ('Создать план урока', 'Создать лекцию',
                       'Создать практическое занятие', 'Создать презентацию', 'Применить переработку')]
        self.assertEqual(len(buttons), 6)
        for button in buttons:
            disabled = next(k.value for k in button.keywords if k.arg == 'disabled')
            self.assertTrue(any(isinstance(n, ast.Name) and n.id == 'generation_limit_reached'
                                for n in ast.walk(disabled)))


if __name__ == '__main__':
    unittest.main()
