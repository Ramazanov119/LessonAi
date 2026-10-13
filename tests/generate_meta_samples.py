"""Generate offline review samples, using the same fixture as regression tests."""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from meta_fixtures import meta_plan
from config.colleges import get_college_config
from services.docx_generator import build_doc
from services.lesson_validation import normalize_meta_lesson


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="lesson_meta")
    prefix = parser.parse_args().prefix
    output = ROOT / 'docs/qa/meta'
    output.mkdir(parents=True, exist_ok=True)
    for language, code in (('Русский', 'ru'), ('Қазақша', 'kk')):
        payload = normalize_meta_lesson(meta_plan(language), language=language,
                                        lesson_type='Лекция', lesson_date=date(2026, 10, 9))
        fields = dict(
            date=date(2026, 10, 9), language=language, course=1, group='IT-1',
            topic='Фишингтік хаттарды анықтау' if code == 'kk' else 'Распознавание фишинговых писем',
            subject='Ақпараттық қауіпсіздік' if code == 'kk' else 'Информационная безопасность',
            teacher='Тест оқытушысы' if code == 'kk' else 'Тестовый преподаватель',
            lesson_type='Дәріс' if code == 'kk' else 'Лекция',
        )
        document = build_doc('План урока', payload, template_path=get_college_config('META')['template'], fields=fields)
        (output / f'{prefix}_{code}.docx').write_bytes(document.getvalue())
        (output / f'{prefix}_{code}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
