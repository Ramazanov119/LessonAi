"""Finite announcement lifecycle, independent of Streamlit reruns and generation."""
from services.lesson_validation import language_code

STATE_KEY = 'release_notice_state'
SEEN_KEY = 'lessonai_seen_releases'


def notice_language(metadata, state):
    for preferences in (state, metadata):
        for key in ('ui_language', 'interface_language', 'language'):
            if preferences.get(key):
                return 'kk' if language_code(preferences[key]) == 'kk' else 'ru'
    return 'ru'


def close_notices_on_navigation(state):
    for notice in state.get(STATE_KEY, {}).values():
        notice['closed'] = True


def prepare_notice(release, account, state, now, mark_seen, *, page='Главная'):
    if page != 'Главная':
        close_notices_on_navigation(state)
        return None
    if not release.get('enabled') or not account.get('id'):
        return None
    user_id = account['id']
    release_id = release['release_id']
    key = f'{user_id}:{release_id}'
    notices = state.setdefault(STATE_KEY, {})
    active = notices.get(key)
    if active is None:
        seen = account.get('metadata', {}).get(SEEN_KEY, [])
        if isinstance(seen, list) and release_id in seen:
            return None
        # Server persistence before display prevents another device/reload replay.
        # Fail closed if storage is unavailable; never falsely claim persistence.
        result = mark_seen(release_id)
        if not result:
            notices[key] = {'closed': True, 'expires_at': now}
            return None
        active = {'closed': False, 'expires_at': now + release['duration_seconds']}
        notices[key] = active
    if active['closed'] or now >= active['expires_at']:
        active['closed'] = True
        return None
    code = notice_language(account.get('metadata', {}), state)
    return {'notice_key': key, 'title': release[f'title_{code}'],
            'message': release[f'message_{code}'], 'language': code,
            'remaining_seconds': active['expires_at'] - now}


def dismiss_notice(state, key):
    active = state.get(STATE_KEY, {}).get(key)
    if active:
        active['closed'] = True
