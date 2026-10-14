"""Small inline notification; its browser timer never blocks the Python app."""
import logging
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from config.releases import CURRENT_RELEASE
from services.release_notice import prepare_notice, dismiss_notice, close_notices_on_navigation, start_notice_timer
from services.supabase_service import SupabaseServiceError

_component = components.declare_component('lessonai_release_notice', path=str(Path(__file__).with_name('release_component')))


def render_release_notice(service, page, release=None):
    release = CURRENT_RELEASE if release is None else release
    if page != 'Главная':
        close_notices_on_navigation(st.session_state)
        return
    if not release.get('enabled'):
        return
    try:
        account = service.get_account_preferences()
        args = prepare_notice(release, account, st.session_state, time.monotonic(), service.mark_release_seen, page=page)
    except SupabaseServiceError:
        logging.getLogger(__name__).warning('Release notice preferences unavailable')
        return
    if args is None:
        return
    result = _component(**args, key='release_notice:' + args['notice_key'], default=None)
    if isinstance(result, dict) and result.get('notice_key') == args['notice_key'] and result.get('reason') == 'shown':
        start_notice_timer(st.session_state, args['notice_key'], time.monotonic())
    if isinstance(result, dict) and result.get('notice_key') == args['notice_key'] and result.get('reason') in ('manual', 'timeout', 'closed'):
        dismiss_notice(st.session_state, args['notice_key'])
        # One finite rerun removes the iframe after dismissal; no generation is called.
        st.rerun()
