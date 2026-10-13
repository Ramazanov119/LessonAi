"""Formatting limited to dynamically populated META text."""
from docx.oxml.ns import qn
from docx.shared import Pt

FONT = 'Times New Roman'


def dynamic_run_font(run):
    size = run.font.size
    # Respect explicit character/paragraph style sizes and their base styles.
    if size is None:
        for style in (run.style, run._parent.style):
            visited = set()
            while style is not None and style.style_id not in visited:
                visited.add(style.style_id)
                if style.font.size is not None:
                    size = style.font.size
                    break
                style = style.base_style
            if size is not None:
                break
    run.font.name = FONT
    fonts = run._r.get_or_add_rPr().rFonts
    for script in ('ascii', 'hAnsi', 'eastAsia', 'cs'):
        fonts.set(qn('w:' + script), FONT)
        # Theme references otherwise allow Word to select a different font.
        theme = qn('w:' + script + 'Theme')
        if theme in fonts.attrib:
            del fonts.attrib[theme]
    run.font.size = size or Pt(12)
    rpr = run._r.get_or_add_rPr()
    complex_size = rpr.find(qn('w:szCs'))
    if complex_size is None:
        from docx.oxml import OxmlElement
        complex_size = OxmlElement('w:szCs')
        rpr.append(complex_size)
    complex_size.set(qn('w:val'), str(round(run.font.size.pt * 2)))
