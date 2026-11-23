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
        profile = dict(is_active=True, subscription_until=None, daily_limit=20,
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
        for limit in (-1, None, True, '20'):
            service, _ = self.service(daily_limit=limit)
            with self.assertRaises(SupabaseServiceError):
                service.profile()

    def test_count_is_scoped_to_user_and_utc_day(self):
        service, client = self.service()
        query = client.table.return_value.select.return_value.eq.return_value
        query.gte.return_value.lt.return_value.execute.return_value.count = 20
        self.assertEqual(service.daily_count('teacher-id'), 20)
        client.table.return_value.select.return_value.eq.assert_called_with('user_id', 'teacher-id')
        self.assertTrue(query.gte.call_args.args[1].endswith('T00:00:00+00:00'))
        service.record_success('teacher-id')
        client.table.return_value.insert.assert_called_once_with({
            'user_id': 'teacher-id', 'agent_type': 'lesson_plan', 'action_type': 'generate',
            'status': 'success', 'model_name': 'unknown', 'duration_ms': 0,
        })


    def test_service_client_used_only_for_writing_log(self):
        service, user_client = self.service()
        log_client = Mock()
        service = PlatformAccess(user_client, log_client=log_client)
        self.assertTrue(service.profile()['allowed'])
        service.record_success('teacher-id', agent_type='lecture', action_type='rework',
                               model_name='test-model', duration_ms=1250)
        log_client.table.assert_called_once_with('generation_logs')
        log_client.table.return_value.insert.assert_called_once_with({
            'user_id': 'teacher-id', 'agent_type': 'lecture', 'action_type': 'rework',
            'status': 'success', 'model_name': 'test-model', 'duration_ms': 1250,
        })
        user_client.table.return_value.insert.assert_not_called()
        log_client.auth.set_session.assert_not_called()

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
        self.assertNotIn(message, str(raised.exception))


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
        service.record_success.assert_not_called()
        service.daily_count.return_value = 19
        self.assertEqual(run(generator), 'material')
        service.record_success.assert_called_once_with('u')
        service.record_success.reset_mock()
        generator.side_effect = RuntimeError('provider failed')
        with self.assertRaises(RuntimeError):
            run(generator)
        service.record_success.assert_not_called()
        service.profile.return_value['allowed'] = False
        with self.assertRaises(Stopped):
            run(generator)
        st.error.assert_called_with('denied')


if __name__ == '__main__':
    unittest.main()
