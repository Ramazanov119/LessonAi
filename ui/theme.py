import streamlit as st


THEME_CSS = """
<style>
:root {
  --bg: #0b0c0f;
  --surface: #111318;
  --surface-elevated: #171a20;
  --input: #12151a;
  --border: rgba(255,255,255,.12);
  --border-hover: rgba(255,255,255,.24);
  --text-primary: #ffffff;
  --text-secondary: #b7bac3;
  --text-muted: #7f838e;
  --accent: #4f7cff;
  --accent-hover: #6d93ff;
  --accent-soft: rgba(79,124,255,.14);
  --etec: #c8424a;
  --meta: #e78638;
  --success: #48b883;
  --warning: #e6a83c;
  --danger: #d75a63;
  --space-1: 8px;
  --space-2: 12px;
  --space-3: 16px;
  --space-4: 24px;
  --space-5: 32px;
}

.stApp { background: var(--bg); color: var(--text-primary); }
.stApp, .stApp input, .stApp button, .stApp select, .stApp textarea { font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
.block-container { max-width: 1040px; padding-top: var(--space-5); padding-bottom: 56px; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"] { max-width: 1040px; }

.ai-edu-brand { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:10px; }
.ai-edu-wordmark { color:var(--text-primary); font-size:1.55rem; font-weight:760; letter-spacing:.01em; line-height:1; }
.ai-edu-wordmark span { color:var(--accent); }
.ai-edu-brand-line { height:5px; border-radius:3px; margin:0 0 28px; background:linear-gradient(90deg, var(--etec) 0%, var(--etec) 34%, #a76558 50%, var(--meta) 66%, var(--meta) 100%); box-shadow:0 0 12px rgba(200,66,74,.12); }
.ai-edu-quota { display:inline-flex; align-items:center; gap:8px; padding:7px 11px; border:1px solid var(--border); border-radius:999px; background:var(--surface); color:var(--text-secondary); font-size:.82rem; font-weight:650; }
.ai-edu-quota strong { color:var(--text-primary); }
.ai-edu-quota.warning { border-color:rgba(230,168,60,.5); color:var(--warning); }
.ai-edu-quota.danger { border-color:rgba(215,90,99,.55); color:var(--danger); }
.ai-edu-lesson-card { border:1px solid var(--border); border-radius:10px; background:var(--surface); padding:18px; min-height:150px; transition:border-color 160ms ease, box-shadow 160ms ease, transform 120ms ease; }
.ai-edu-lesson-card:hover { border-color:rgba(79,124,255,.55); box-shadow:0 8px 22px rgba(0,0,0,.2); transform:translateY(-1px); }
.ai-edu-lesson-card h3 { margin:0 0 6px; font-size:1.05rem; }
.ai-edu-card-subtitle, .ai-edu-card-meta, .ai-edu-card-kit { margin:4px 0; color:var(--text-secondary); font-size:.86rem; }
.ai-edu-card-kit strong { color:var(--accent-hover); }

h1, h2, h3 { color: var(--text-primary); letter-spacing: 0; }
[data-testid="stMarkdownContainer"] p, label, [data-testid="stCaptionContainer"] { color: var(--text-secondary); }

/* Compact, consistent controls with a restrained focus ring. */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stDateInput"] input,
[data-baseweb="select"] > div {
  min-height: 40px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--input);
  color: var(--text-primary);
  transition: border-color 180ms ease, box-shadow 180ms ease, background 180ms ease;
}
[data-testid="stTextInput"] input:hover,
[data-testid="stNumberInput"] input:hover,
[data-testid="stDateInput"] input:hover,
[data-baseweb="select"] > div:hover { border-color: var(--border-hover); }
[data-testid="stTextInput"] input::placeholder,
[data-testid="stNumberInput"] input::placeholder,
[data-testid="stDateInput"] input::placeholder { color: var(--text-muted); opacity: 1; }
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stDateInput"] input:focus,
[data-baseweb="base-input"]:focus-within,
[data-baseweb="select"]:focus-within > div {
  border-color: var(--accent);
  background: #171b22;
  box-shadow: 0 0 0 3px rgba(15, 107, 143, .13);
  outline: none;
}
[data-baseweb="select"] span, [data-baseweb="select"] input { color: var(--text-primary); }
[data-baseweb="popover"], [data-baseweb="menu"] { background: var(--surface-elevated); color: var(--text-primary); }
[data-baseweb="menu"] li:hover { background: var(--accent-soft); }

/* Choices read as compact selectable chips rather than isolated radio dots. */
[data-testid="stRadio"] > div[role="radiogroup"] { gap: 8px; }
[data-testid="stRadio"] label {
  min-height: 40px;
  box-sizing: border-box;
  margin: 0;
  padding: 9px 14px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text-secondary);
  transition: border-color 160ms ease, background 160ms ease, box-shadow 160ms ease, transform 120ms ease;
}
[data-testid="stRadio"] label:hover { border-color: var(--accent); background: var(--accent-soft); transform: translateY(-1px); }
[data-testid="stRadio"] label:has(input:checked) {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent-hover);
  box-shadow: 0 0 0 2px rgba(15, 107, 143, .1);
}
[data-testid="stRadio"] label:has(input:focus-visible) { box-shadow: 0 0 0 3px rgba(15, 107, 143, .18); }

/* Primary actions are filled and always use a readable white-on-color pair. */
[data-testid="stButton"] > button,
[data-testid="stDownloadButton"] > button {
  min-height: 40px;
  padding: 8px 16px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text-primary);
  font-weight: 650;
  transition: background 160ms ease, border-color 160ms ease, box-shadow 160ms ease, transform 120ms ease;
}
[data-testid="stButton"] > button:hover,
[data-testid="stDownloadButton"] > button:hover {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent-hover);
  box-shadow: 0 4px 12px rgba(15, 71, 94, .10);
}
[data-testid="stButton"] > button p,
[data-testid="stDownloadButton"] > button p,
[data-testid="stBaseButton-primary"] p { color: inherit !important; }
[data-testid="stButton"] > button[kind="primary"] { border-color: var(--accent); background: var(--accent); color: #ffffff; box-shadow: 0 3px 8px rgba(15, 71, 94, .12); }
[data-testid="stButton"] > button[kind="primary"]:hover { border-color: var(--accent-hover); background: var(--accent-hover); color: #ffffff; }
[data-testid="stButton"] > button[kind="tertiary"] { border-color: transparent; background: transparent; color: var(--text-secondary); }
[data-testid="stButton"] > button[kind="tertiary"]:hover { background: var(--accent-soft); color: var(--accent-hover); box-shadow: none; }
[data-testid="stButton"] > button:active,
[data-testid="stDownloadButton"] > button:active { transform: translateY(1px); box-shadow: none; }
[data-testid="stButton"] > button:focus-visible,
[data-testid="stDownloadButton"] > button:focus-visible { box-shadow: 0 0 0 3px rgba(15, 107, 143, .2); }
[data-testid="stButton"] > button:disabled,
[data-testid="stDownloadButton"] > button:disabled { background: #dfe5e9; border-color: #dfe5e9; color: #71808b; }

[data-testid="stTabs"] { width: calc(100% - 24px); max-width: 480px; box-sizing: border-box; margin: 0 auto; padding: 20px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); box-shadow: 0 12px 30px rgba(0,0,0,.24); }
[data-testid="stTabs"] [data-baseweb="tab-list"] { gap: 4px; }
[data-testid="stTabs"] [data-baseweb="tab"] { color: var(--text-secondary); }
[data-testid="stTabs"] [aria-selected="true"] { color: var(--accent); }
[data-testid="stExpander"] { border-color: var(--border); border-radius: 6px; background: var(--surface); }
[data-testid="stStatusWidget"] { border-color: var(--border); background: var(--surface); }
[data-testid="stAlert"] { background: var(--surface-elevated); color: var(--text-secondary); border-color: var(--border); }
[data-testid="stStatusWidget"] summary, [data-testid="stStatusWidget"] div { color: var(--text-secondary); }

@media (max-width: 700px) {
  .block-container { padding: 16px 12px 40px; }
  [data-testid="stTabs"] { padding: 14px; }
  [data-testid="stRadio"] label { width: 100%; }
}
</style>
"""


def apply_theme():
    st.markdown(THEME_CSS, unsafe_allow_html=True)
