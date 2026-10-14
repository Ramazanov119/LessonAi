import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from config.releases import CURRENT_RELEASE
from services.release_notice import prepare_notice, dismiss_notice, SEEN_KEY, STATE_KEY, start_notice_timer
from services.supabase_service import SupabaseService, SupabaseServiceError


def config(**changes):
    return {**CURRENT_RELEASE, 'enabled': True, **changes}


def account(seen=None, user='one', language='Русский'):
    return {'id': user, 'metadata': {SEEN_KEY: seen or [], 'ui_language': language}}


class ReleaseNoticeTest(unittest.TestCase):
    def test_only_homepage_displays_and_marks_release_once(self):
        state, mark = {}, Mock(return_value=True)
        self.assertIsNone(prepare_notice(config(), account(), state, 10, mark, page='Мои занятия'))
        mark.assert_not_called()
        first = prepare_notice(config(), account(), state, 10, mark)
        self.assertEqual(first['remaining_seconds'], 15)
        self.assertEqual(first['title'], 'LessonAI обновлён!')
        start_notice_timer(state, first['notice_key'], 10)
        rerun = prepare_notice(config(), account(), state, 12, mark)
        self.assertEqual(rerun['remaining_seconds'], 13)
        self.assertEqual(rerun['notice_key'], first['notice_key'])
        mark.assert_called_once_with(CURRENT_RELEASE['release_id'])

    def test_expires_at_15_seconds_without_python_sleep(self):
        state, mark = {}, Mock(return_value=True)
        first = prepare_notice(config(), account(), state, 100, mark)
        start_notice_timer(state, first['notice_key'], 100)
        self.assertIsNotNone(prepare_notice(config(), account(), state, 114.99, mark))
        self.assertIsNone(prepare_notice(config(), account(), state, 115, mark))
        self.assertIsNone(prepare_notice(config(), account(), state, 200, mark))

    def test_timer_starts_at_browser_visibility_not_server_render(self):
        state, mark = {}, Mock(return_value=True)
        first = prepare_notice(config(), account(), state, 100, mark)
        self.assertIsNotNone(prepare_notice(config(), account(), state, 110, mark))
        start_notice_timer(state, first['notice_key'], 110)
        self.assertIsNotNone(prepare_notice(config(), account(), state, 124.99, mark))
        self.assertIsNone(prepare_notice(config(), account(), state, 125, mark))

    def test_repeated_browser_ack_does_not_reset_timer(self):
        state, mark = {}, Mock(return_value=True)
        first = prepare_notice(config(), account(), state, 100, mark)
        start_notice_timer(state, first['notice_key'], 100)
        start_notice_timer(state, first['notice_key'], 110)
        self.assertIsNone(prepare_notice(config(), account(), state, 115, mark))

    def test_manual_close_and_navigation_never_replay(self):
        for mode in ('manual', 'navigation'):
            with self.subTest(mode=mode):
                state, mark = {}, Mock(return_value=True)
                first = prepare_notice(config(), account(), state, 10, mark)
                if mode == 'manual':
                    dismiss_notice(state, first['notice_key'])
                else:
                    prepare_notice(config(), account(), state, 11, mark, page='Создать занятие')
                self.assertIsNone(prepare_notice(config(), account(), state, 12, mark))
                mark.assert_called_once()

    def test_seen_account_other_device_and_next_version(self):
        seen = [CURRENT_RELEASE['release_id']]
        mark = Mock(return_value=True)
        self.assertIsNone(prepare_notice(config(), account(seen), {}, 0, mark))
        mark.assert_not_called()
        self.assertIsNotNone(prepare_notice(config(release_id='next_version'), account(seen), {}, 0, mark))
        mark.assert_called_once_with('next_version')

    def test_language_settings_and_separate_accounts(self):
        state, mark = {'ui_language': 'Қазақша'}, Mock(return_value=True)
        one = prepare_notice(config(), account(), state, 0, mark)
        self.assertEqual(one['title'], 'LessonAI жаңартылды!')
        dismiss_notice(state, one['notice_key'])
        self.assertIsNotNone(prepare_notice(config(), account(user='two'), state, 2, mark))
        self.assertEqual(mark.call_count, 2)

    def test_disabled_or_failed_storage_does_not_display(self):
        mark = Mock(return_value=False)
        self.assertIsNone(prepare_notice(config(enabled=False), account(), {}, 0, mark))
        mark.assert_not_called()
        self.assertIsNone(prepare_notice(config(), account(), {}, 0, mark))

    def test_auth_metadata_write_is_scoped_and_confirmed(self):
        client = Mock()
        client.auth.get_user.return_value.user = SimpleNamespace(id='one', user_metadata={
            SEEN_KEY: ['previous'], 'full_name': 'Teacher', 'college': 'Q', 'role': 'teacher'})
        client.auth.update_user.return_value.user = SimpleNamespace(user_metadata={SEEN_KEY: ['previous', 'new']})
        service = SupabaseService(client)
        self.assertTrue(service.mark_release_seen('new'))
        client.auth.update_user.assert_called_once_with({'data': {SEEN_KEY: ['previous', 'new']}})
        client.table.assert_not_called()
        client.rpc.assert_not_called()

    def test_existing_seen_version_does_not_write_again(self):
        client = Mock()
        client.auth.get_user.return_value.user = SimpleNamespace(id='one', user_metadata={SEEN_KEY: ['old']})
        self.assertFalse(SupabaseService(client).mark_release_seen('old'))
        client.auth.update_user.assert_not_called()

    def test_unconfirmed_storage_is_reported(self):
        client = Mock()
        client.auth.get_user.return_value.user = SimpleNamespace(id='one', user_metadata={})
        client.auth.update_user.return_value.user = None
        with self.assertRaises(SupabaseServiceError):
            SupabaseService(client).mark_release_seen('new')

    def test_streamlit_component_mount_and_manual_dismiss(self):
        from ui import release_notice as ui
        service = Mock()
        service.get_account_preferences.return_value = account()
        service.mark_release_seen.return_value = True
        state = {}
        with patch.object(ui.st, 'session_state', state), patch.object(ui, '_component', return_value=None) as component:
            ui.render_release_notice(service, 'Главная', config())
            component.assert_called_once()
            key = component.call_args.kwargs['notice_key']
            component.return_value = {'notice_key': key, 'reason': 'manual'}
            with patch.object(ui.st, 'rerun') as rerun:
                ui.render_release_notice(service, 'Главная', config())
                rerun.assert_called_once()
            component.reset_mock()
            ui.render_release_notice(service, 'Главная', config())
            component.assert_not_called()

    def test_interface_contains_real_timer_close_and_mobile_css(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / 'ui/release_component'
        js = (root / 'notice.js').read_text()
        self.assertIn('setTimeout', js)
        self.assertIn('notice.hidden = true', js)
        self.assertIn("hide('manual')", js)
        self.assertIn('setFrameHeight', js)
        self.assertIn('@media(max-width:480px)', (root / 'index.html').read_text())
