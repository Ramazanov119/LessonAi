"""Localize fixed lesson-template labels before inserting user/AI content."""
import json
import re
from functools import lru_cache
from pathlib import Path

from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.table import _Cell

from services.lesson_validation import language_code


def _key(text):
    return re.sub(r'\s+', ' ', text).strip()


@lru_cache(maxsize=1)
def _labels():
    return json.loads((Path(__file__).parent / 'locales' / 'lesson_template_labels.json').read_text())


def _replace_paragraph(paragraph, text):
    # Keep paragraph and first-run properties; do not touch logos or drawings.
    runs = [run for run in paragraph.runs if not run._r.xpath('.//w:drawing | .//w:pict')]
    run = runs[0] if runs else paragraph.add_run()
    run.text = text
    for other in runs[1:]:
        other.text = ''


def localize_lesson_template(doc, language='Русский'):
    code = language_code(language)
    if code not in ('kk', 'ru'):
        return
    labels = _labels()
    roots = [doc.element]
    # Only existing parts: accessing section.header can create new package parts.
    for relationship in doc.part.rels.values():
        if relationship.reltype.endswith(('/header', '/footer')):
            roots.append(relationship.target_part.element)
    handled = set()
    for root in roots:
        if root in handled:
            continue
        handled.add(root)
        localized_cells = set()
        for element in root.xpath('.//w:tc'):
            cell = _Cell(element, doc)
            translation = labels.get(_key(cell.text))
            if translation is None:
                continue
            _replace_paragraph(cell.paragraphs[0], translation[code])
            for paragraph in cell.paragraphs[1:]:
                paragraph._p.getparent().remove(paragraph._p)
            localized_cells.add(element)
        # Includes text outside tables, and table paragraphs with placeholders.
        seen = set()
        for element in list(root.xpath('.//w:p')):
            if any(parent in localized_cells for parent in element.iterancestors(qn('w:tc'))):
                continue
            paragraph = Paragraph(element, doc)
            translation = labels.get(_key(paragraph.text))
            if translation is None:
                continue
            text = translation[code]
            identity = (element.getparent(), text)
            if not text or identity in seen:
                # A cell must retain at least one paragraph for valid OOXML.
                parent = element.getparent()
                if parent.tag != qn('w:tc') or len(parent.findall(qn('w:p'))) > 1:
                    parent.remove(element)
                else:
                    _replace_paragraph(paragraph, '')
                continue
            seen.add(identity)
            _replace_paragraph(paragraph, text)
