"""Explicit local-only failure capture; never enabled by default in production."""
import os
from pathlib import Path


def meta_diagnostic_directory():
    if os.getenv('LESSONAI_ENV', '').lower() not in ('development', 'local', 'test'):
        return None
    if os.getenv('LESSONAI_META_DIAGNOSTICS', '').lower() not in ('1', 'true'):
        return None
    return Path(os.getenv('LESSONAI_META_DIAGNOSTIC_DIR', '/private/tmp/lessonai-meta-diagnostics'))


def meta_response_directory():
    """Temporary opt-in paired captures, local only and ignored by Git."""
    if os.getenv('LESSONAI_ENV', '').lower() not in ('development', 'local', 'test'):
        return None
    if os.getenv('LESSONAI_META_CAPTURE_RESPONSES', '').lower() not in ('1', 'true'):
        return None
    return Path(__file__).resolve().parents[1] / 'docs/qa/meta/debug'
