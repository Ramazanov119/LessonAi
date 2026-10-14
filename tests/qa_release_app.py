"""Offline UI harness: streamlit run tests/qa_release_app.py (no Supabase/AI calls)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st
from config.releases import CURRENT_RELEASE
from ui.release_notice import render_release_notice
from services.release_notice import SEEN_KEY

st.set_page_config(page_title='LessonAI notification QA', layout='centered')


class MemoryAccount:
    def __init__(self):
        self.seen = {}
        self.user = 'qa-user-1'

    def get_account_preferences(self):
        return {'id': self.user, 'metadata': {SEEN_KEY: list(self.seen.get(self.user, []))}}

    def mark_release_seen(self, release_id):
        self.seen.setdefault(self.user, set()).add(release_id)
        return True


@st.cache_resource
def service():
    return MemoryAccount()


memory = service()
controls = st.expander('Test settings', expanded=False) if st.query_params.get('qa_mobile') else st.sidebar
user = controls.selectbox('Test account', ['qa-user-1', 'qa-user-2'])
memory.user = user
page = controls.radio('Page', ['Главная', 'Мои занятия', 'Создать занятие'])
st.session_state['ui_language'] = controls.selectbox('Interface language', ['Русский', 'Қазақша'], index=1 if st.query_params.get('qa_language') == 'kk' else 0)
version = controls.text_input('Release ID', value=st.query_params.get('qa_release_id', CURRENT_RELEASE['release_id']))
render_release_notice(memory, page, {**CURRENT_RELEASE, 'enabled': True, 'release_id': version})
st.title('LessonAI offline notification test')
st.write('This button and input remain usable during the timer.')
st.text_input('Interactive field')
if st.button('Mock generation'):
    st.session_state['mock_generations'] = st.session_state.get('mock_generations', 0) + 1
st.caption(f"Mock generations: {st.session_state.get('mock_generations', 0)}")
st.caption('Seen: ' + ', '.join(sorted(memory.seen.get(user, []))))
