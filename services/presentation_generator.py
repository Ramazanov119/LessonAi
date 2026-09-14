import re
from io import BytesIO
from typing import Iterable, Optional

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from models.generation import NBDeck, NBSlide, PresentationSlide
from services.palette import (
    ACCENT,
    ACCENT_SOFT,
    BACKGROUND,
    BODY_SIZE,
    BORDER,
    CARD,
    DIVIDER,
    FONT_FAMILY,
    GUTTER,
    HEADING_SIZE,
    MARGIN,
    SLIDE_HEIGHT,
    SLIDE_WIDTH,
    SMALL_SIZE,
    SUBTITLE_SIZE,
    SURFACE,
    SURFACE_ELEVATED,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    TITLE_SIZE,
    accent_for,
    college_accent,
)


def _init_presentation() -> Presentation:
    """Initialize a python-pptx Presentation configured for 16:9 widescreen."""
    prs = Presentation()
    prs.slide_width = SLIDE_WIDTH
    prs.slide_height = SLIDE_HEIGHT
    return prs


def _create_slide(prs: Presentation, bg_color: RGBColor = BACKGROUND):
    """Create a blank slide with a solid dark background."""
    blank_layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[-1]
    slide = prs.slides.add_slide(blank_layout)

    # Set native slide background fill if supported
    try:
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = bg_color
    except Exception:
        pass

    # Ensure consistent dark background across all PowerPoint viewers
    bg_shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height
    )
    bg_shape.fill.solid()
    bg_shape.fill.fore_color.rgb = bg_color
    bg_shape.line.fill.background()
    return slide


def _render_header(
    slide,
    title: str,
    subtitle: str = "",
    tag: str = "",
    accent_color: RGBColor = ACCENT,
) -> None:
    """Render a standard NotebookLM-style slide header."""
    header_box = slide.shapes.add_textbox(
        MARGIN, MARGIN, SLIDE_WIDTH - (MARGIN * 2), Inches(1.1)
    )
    tf = header_box.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0)
    tf.margin_top = Inches(0)
    tf.margin_right = Inches(0)
    tf.margin_bottom = Inches(0)

    p_idx = 0
    if tag:
        p_tag = tf.paragraphs[0]
        p_tag.text = tag.upper()
        p_tag.font.name = FONT_FAMILY
        p_tag.font.size = SMALL_SIZE
        p_tag.font.bold = True
        p_tag.font.color.rgb = accent_color
        p_tag.space_after = Pt(4)
        p_idx += 1

    if p_idx == 0:
        p_title = tf.paragraphs[0]
    else:
        p_title = tf.add_paragraph()

    p_title.text = title
    p_title.font.name = FONT_FAMILY
    p_title.font.size = HEADING_SIZE
    p_title.font.bold = True
    p_title.font.color.rgb = TEXT_PRIMARY

    if subtitle:
        p_sub = tf.add_paragraph()
        p_sub.text = subtitle
        p_sub.font.name = FONT_FAMILY
        p_sub.font.size = SMALL_SIZE
        p_sub.font.color.rgb = TEXT_SECONDARY
        p_sub.space_before = Pt(4)


def _render_footer(
    slide,
    text: str = "",
    slide_index: Optional[int] = None,
    total_slides: Optional[int] = None,
) -> None:
    """Render a subtle divider and footer with optional slide numbering."""
    footer_top = SLIDE_HEIGHT - MARGIN - Inches(0.35)
    footer_width = SLIDE_WIDTH - (MARGIN * 2)

    # Subtle divider
    divider = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, MARGIN, footer_top - Pt(8), footer_width, Pt(1)
    )
    divider.fill.solid()
    divider.fill.fore_color.rgb = DIVIDER
    divider.line.fill.background()

    # Left text (subject, lesson metadata)
    if text:
        left_box = slide.shapes.add_textbox(
            MARGIN, footer_top, footer_width * 0.75, Inches(0.35)
        )
        ltf = left_box.text_frame
        ltf.word_wrap = True
        ltf.margin_left = Inches(0)
        ltf.margin_top = Inches(0)
        ltf.margin_right = Inches(0)
        ltf.margin_bottom = Inches(0)
        lp = ltf.paragraphs[0]
        lp.text = text
        lp.font.name = FONT_FAMILY
        lp.font.size = SMALL_SIZE
        lp.font.color.rgb = TEXT_MUTED

    # Right text (slide counter)
    if slide_index is not None:
        right_box = slide.shapes.add_textbox(
            MARGIN + footer_width * 0.75, footer_top, footer_width * 0.25, Inches(0.35)
        )
        rtf = right_box.text_frame
        rtf.word_wrap = True
        rtf.margin_left = Inches(0)
        rtf.margin_top = Inches(0)
        rtf.margin_right = Inches(0)
        rtf.margin_bottom = Inches(0)
        rp = rtf.paragraphs[0]
        rp.text = (
            f"{slide_index:02d} / {total_slides:02d}"
            if total_slides
            else f"{slide_index:02d}"
        )
        rp.alignment = PP_ALIGN.RIGHT
        rp.font.name = FONT_FAMILY
        rp.font.size = SMALL_SIZE
        rp.font.color.rgb = TEXT_MUTED


def _render_card(
    slide,
    left: Inches,
    top: Inches,
    width: Inches,
    height: Inches,
    bg_color: RGBColor = CARD,
    border_color: Optional[RGBColor] = BORDER,
):
    """Render a rounded card container for organizing content."""
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    card.fill.solid()
    card.fill.fore_color.rgb = bg_color
    if border_color:
        card.line.color.rgb = border_color
        card.line.width = Pt(1)
    else:
        card.line.fill.background()

    tf = card.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.2)
    tf.margin_right = Inches(0.2)
    tf.margin_top = Inches(0.2)
    tf.margin_bottom = Inches(0.2)
    return card


def _render_highlight_box(
    slide,
    left: Inches,
    top: Inches,
    width: Inches,
    height: Inches,
    text: str,
    title: str = "ВАЖНО",
    accent_color: RGBColor = ACCENT,
    bg_color: RGBColor = CARD,
):
    """Render an accent callout card with a vertical accent bar on the left."""
    card = _render_card(slide, left, top, width, height, bg_color=bg_color, border_color=BORDER)

    # Accent bar on the left edge
    bar_width = Inches(0.08)
    bar = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, bar_width, height)
    bar.fill.solid()
    bar.fill.fore_color.rgb = accent_color
    bar.line.fill.background()

    # Content text box inside the card
    text_box = slide.shapes.add_textbox(
        left + Inches(0.25),
        top + Inches(0.15),
        width - Inches(0.4),
        height - Inches(0.3),
    )
    tf = text_box.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0)
    tf.margin_top = Inches(0)
    tf.margin_right = Inches(0)
    tf.margin_bottom = Inches(0)

    p_idx = 0
    if title:
        p_title = tf.paragraphs[0]
        p_title.text = title.upper()
        p_title.font.name = FONT_FAMILY
        p_title.font.size = SMALL_SIZE
        p_title.font.bold = True
        p_title.font.color.rgb = accent_color
        p_title.space_after = Pt(4)
        p_idx += 1

    if p_idx == 0:
        p_text = tf.paragraphs[0]
    else:
        p_text = tf.add_paragraph()

    p_text.text = text
    p_text.font.name = FONT_FAMILY
    p_text.font.size = BODY_SIZE
    p_text.font.color.rgb = TEXT_PRIMARY

    return card


def _render_title_slide(
    slide,
    deck: NBDeck,
    slide_data: NBSlide,
    college_color: RGBColor,
) -> None:
    """Render a NotebookLM-style title slide with college branding and info cards."""
    # College accent indicator bar at the top
    accent_bar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        MARGIN,
        MARGIN + Inches(0.1),
        Inches(1.5),
        Pt(4),
    )
    accent_bar.fill.solid()
    accent_bar.fill.fore_color.rgb = college_color
    accent_bar.line.fill.background()

    # Subject & college badge/tag
    tag_box = slide.shapes.add_textbox(
        MARGIN,
        MARGIN + Inches(0.25),
        SLIDE_WIDTH - (MARGIN * 2),
        Inches(0.4),
    )
    ttf = tag_box.text_frame
    ttf.word_wrap = True
    ttf.margin_left = Inches(0)
    ttf.margin_top = Inches(0)
    ttf.margin_right = Inches(0)
    ttf.margin_bottom = Inches(0)
    tp = ttf.paragraphs[0]
    parts = []
    if deck.college:
        parts.append(deck.college.upper())
    if deck.subject:
        parts.append(deck.subject.upper())
    tp.text = "  /  ".join(parts) if parts else "УЧЕБНЫЙ МАТЕРИАЛ"
    tp.font.name = FONT_FAMILY
    tp.font.size = SMALL_SIZE
    tp.font.bold = True
    tp.font.color.rgb = college_color

    # Hero title and subtitle
    title_text = slide_data.title or deck.title
    subtitle_text = slide_data.subtitle

    title_box = slide.shapes.add_textbox(
        MARGIN,
        MARGIN + Inches(0.85),
        SLIDE_WIDTH - (MARGIN * 2),
        Inches(3.8),
    )
    tf = title_box.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0)
    tf.margin_top = Inches(0)
    tf.margin_right = Inches(0)
    tf.margin_bottom = Inches(0)

    p_title = tf.paragraphs[0]
    p_title.text = title_text
    p_title.font.name = FONT_FAMILY
    p_title.font.size = TITLE_SIZE
    p_title.font.bold = True
    p_title.font.color.rgb = TEXT_PRIMARY
    p_title.space_after = Pt(12)

    if subtitle_text:
        p_sub = tf.add_paragraph()
        p_sub.text = subtitle_text
        p_sub.font.name = FONT_FAMILY
        p_sub.font.size = SUBTITLE_SIZE
        p_sub.font.color.rgb = TEXT_SECONDARY

    # Bottom info cards (Teacher, Group, Date)
    cards_data = (
        ("ПРЕПОДАВАТЕЛЬ", deck.teacher or "Не указан"),
        ("ГРУППА", deck.group or "Не указана"),
        ("ДАТА", deck.date or "Не указана"),
    )
    num_cards = len(cards_data)
    card_height = Inches(1.4)
    card_top = SLIDE_HEIGHT - MARGIN - card_height
    total_gutters = (num_cards - 1) * GUTTER
    card_width = (SLIDE_WIDTH - (MARGIN * 2) - total_gutters) / num_cards

    for i, (label, value) in enumerate(cards_data):
        c_left = MARGIN + i * (card_width + GUTTER)
        card = _render_card(
            slide,
            c_left,
            card_top,
            card_width,
            card_height,
            bg_color=CARD,
            border_color=BORDER,
        )
        ctf = card.text_frame
        ctf.word_wrap = True
        ctf.margin_left = Inches(0.25)
        ctf.margin_top = Inches(0.2)
        ctf.margin_right = Inches(0.25)
        ctf.margin_bottom = Inches(0.2)

        p_label = ctf.paragraphs[0]
        p_label.text = label
        p_label.font.name = FONT_FAMILY
        p_label.font.size = Pt(11)
        p_label.font.bold = True
        p_label.font.color.rgb = college_color
        p_label.space_after = Pt(6)

        p_val = ctf.add_paragraph()
        p_val.text = value
        p_val.font.name = FONT_FAMILY
        p_val.font.size = Pt(16)
        p_val.font.bold = True
        p_val.font.color.rgb = TEXT_PRIMARY


def _render_overview_slide(
    slide,
    deck: NBDeck,
    slide_data: NBSlide,
    college_color: RGBColor,
) -> None:
    """Render a NotebookLM-style overview / roadmap slide with a grid of numbered cards."""
    # Header
    title = slide_data.title or "План занятия"
    subtitle = slide_data.subtitle or "Структура и ключевые блоки учебного материала"
    _render_header(slide, title=title, subtitle=subtitle, tag="ОБЗОР", accent_color=college_color)

    # Extract structured blocks from sections or items
    blocks: list[tuple[str, str]] = []
    if slide_data.sections:
        for heading, body in slide_data.sections:
            clean_h = re.sub(r"^\d+[\.\)]\s*", "", str(heading).strip())
            blocks.append((clean_h, str(body).strip()))
    elif slide_data.items:
        for item in slide_data.items:
            item_str = str(item).strip()
            if " - " in item_str:
                h, b = item_str.split(" - ", 1)
            elif ": " in item_str:
                h, b = item_str.split(": ", 1)
            else:
                h, b = item_str, ""
            clean_h = re.sub(r"^\d+[\.\)]\s*", "", h.strip())
            blocks.append((clean_h, b.strip()))

    if not blocks:
        blocks = [
            ("Введение", "Цели и задачи занятия"),
            ("Теоретический базис", "Основные концепции и определения"),
            ("Практический разбор", "Примеры, сценарии и задачи"),
            ("Итоги и выводы", "Закрепление материала"),
        ]

    # Limit to maximum 6 cards to maintain visual clarity
    display_blocks = blocks[:6]
    n = len(display_blocks)

    available_width = SLIDE_WIDTH - (MARGIN * 2)
    content_top = Inches(1.6)
    footer_margin = Inches(0.55)
    max_bottom = SLIDE_HEIGHT - MARGIN - footer_margin
    available_height = max_bottom - content_top

    # Highlight box at the bottom if present
    if slide_data.highlight:
        hl_height = Inches(0.95)
        hl_top = max_bottom - hl_height
        _render_highlight_box(
            slide,
            MARGIN,
            hl_top,
            available_width,
            hl_height,
            slide_data.highlight,
            title="КЛЮЧЕВОЙ РЕЗУЛЬТАТ",
            accent_color=college_color,
        )
        grid_height = hl_top - GUTTER - content_top
    else:
        grid_height = available_height

    # Grid configuration (columns & rows)
    if n <= 3:
        cols = max(1, n)
        rows = 1
    elif n == 4:
        cols = 2
        rows = 2
    else:
        cols = 3
        rows = 2

    total_col_gutters = (cols - 1) * GUTTER
    card_width = (available_width - total_col_gutters) / cols
    total_row_gutters = (rows - 1) * GUTTER
    card_height = (grid_height - total_row_gutters) / rows

    for i, (heading, body) in enumerate(display_blocks):
        r = i // cols
        c = i % cols
        c_left = MARGIN + c * (card_width + GUTTER)
        c_top = content_top + r * (card_height + GUTTER)

        card = _render_card(
            slide, c_left, c_top, card_width, card_height, bg_color=CARD, border_color=BORDER
        )
        ctf = card.text_frame
        ctf.word_wrap = True
        ctf.margin_left = Inches(0.3)
        ctf.margin_top = Inches(0.22)
        ctf.margin_right = Inches(0.3)
        ctf.margin_bottom = Inches(0.22)

        # Number 01, 02, 03...
        p_num = ctf.paragraphs[0]
        p_num.text = f"{i + 1:02d}"
        p_num.font.name = FONT_FAMILY
        p_num.font.size = Pt(22)
        p_num.font.bold = True
        p_num.font.color.rgb = college_color
        p_num.space_after = Pt(4)

        # Block heading
        p_title = ctf.add_paragraph()
        p_title.text = heading
        p_title.font.name = FONT_FAMILY
        p_title.font.size = Pt(17)
        p_title.font.bold = True
        p_title.font.color.rgb = TEXT_PRIMARY
        p_title.space_after = Pt(4)

        # Block body / description
        if body:
            p_desc = ctf.add_paragraph()
            p_desc.text = body
            p_desc.font.name = FONT_FAMILY
            p_desc.font.size = Pt(13)
            p_desc.font.color.rgb = TEXT_SECONDARY


def _render_concept_slide(
    slide,
    deck: NBDeck,
    slide_data: NBSlide,
    college_color: RGBColor,
) -> None:
    """Render a NotebookLM-style concept slide with a ~60/40 two-column layout."""
    # Header
    title = slide_data.title or "Ключевая концепция"
    subtitle = slide_data.subtitle or "Теоретические основы и главные принципы"
    _render_header(slide, title=title, subtitle=subtitle, tag="КОНЦЕПЦИЯ", accent_color=college_color)

    available_width = SLIDE_WIDTH - (MARGIN * 2)
    content_top = Inches(1.6)
    footer_margin = Inches(0.55)
    max_bottom = SLIDE_HEIGHT - MARGIN - footer_margin
    available_height = max_bottom - content_top

    # 60/40 horizontal split
    left_width = (available_width - GUTTER) * 0.58
    right_width = available_width - GUTTER - left_width
    right_left = MARGIN + left_width + GUTTER

    # Extract primary concept and secondary theses
    main_heading = ""
    main_body = ""
    secondary_blocks: list[tuple[str, str]] = []

    if slide_data.sections:
        main_heading = str(slide_data.sections[0][0]).strip()
        main_body = str(slide_data.sections[0][1]).strip()
        for heading, body in slide_data.sections[1:]:
            secondary_blocks.append((str(heading).strip(), str(body).strip()))

    # Supplement secondary points from items if needed
    if slide_data.items:
        if not main_heading and not main_body:
            main_heading = "Суть концепции"
            main_body = str(slide_data.items[0]).strip()
            item_source = slide_data.items[1:]
        else:
            item_source = slide_data.items

        for it in item_source:
            if len(secondary_blocks) >= 3:
                break
            it_str = str(it).strip()
            if " - " in it_str:
                h, b = it_str.split(" - ", 1)
            elif ": " in it_str:
                h, b = it_str.split(": ", 1)
            else:
                h, b = "Ключевой аспект", it_str
            secondary_blocks.append((h.strip(), b.strip()))

    if not main_heading:
        main_heading = title
    if not main_body:
        main_body = subtitle or "Подробное объяснение концепции, ее роли и взаимосвязи с другими элементами темы."

    if not secondary_blocks:
        secondary_blocks = [
            ("Назначение", "Определяет базовые правила и принципы функционирования архитектуры."),
            ("Преимущества", "Упрощает масштабирование, тестирование и поддержку систем."),
        ]

    sec_blocks_display = secondary_blocks[:3]
    if len(sec_blocks_display) < 2:
        sec_blocks_display.append(
            ("Практическое значение", "Применяется в реальных сценариях проектирования и разработки.")
        )

    # --- LEFT COLUMN: Main Card (+ Accent Highlight Box if present) ---
    has_highlight = bool(slide_data.highlight and slide_data.highlight.strip())
    if has_highlight:
        hl_height = Inches(1.2)
        main_card_height = available_height - hl_height - GUTTER
    else:
        main_card_height = available_height

    main_card = _render_card(
        slide,
        MARGIN,
        content_top,
        left_width,
        main_card_height,
        bg_color=CARD,
        border_color=BORDER,
    )
    mtf = main_card.text_frame
    mtf.word_wrap = True
    mtf.margin_left = Inches(0.35)
    mtf.margin_top = Inches(0.3)
    mtf.margin_right = Inches(0.35)
    mtf.margin_bottom = Inches(0.3)

    # Badge in main card
    p_badge = mtf.paragraphs[0]
    p_badge.text = "ОСНОВНОЕ ПОЛОЖЕНИЕ"
    p_badge.font.name = FONT_FAMILY
    p_badge.font.size = Pt(11)
    p_badge.font.bold = True
    p_badge.font.color.rgb = college_color
    p_badge.space_after = Pt(8)

    # Main heading
    p_h = mtf.add_paragraph()
    p_h.text = main_heading
    p_h.font.name = FONT_FAMILY
    p_h.font.size = Pt(22)
    p_h.font.bold = True
    p_h.font.color.rgb = TEXT_PRIMARY
    p_h.space_after = Pt(8)

    # Main body
    p_b = mtf.add_paragraph()
    p_b.text = main_body
    p_b.font.name = FONT_FAMILY
    p_b.font.size = Pt(15)
    p_b.font.color.rgb = TEXT_SECONDARY

    # Highlight box underneath main card
    if has_highlight:
        hl_top = content_top + main_card_height + GUTTER
        _render_highlight_box(
            slide,
            MARGIN,
            hl_top,
            left_width,
            hl_height,
            slide_data.highlight,
            title="ВАЖНЫЙ ВЫВОД",
            accent_color=college_color,
            bg_color=CARD,
        )

    # --- RIGHT COLUMN: 2-3 Secondary Thesis Cards ---
    k = len(sec_blocks_display)
    total_r_gutters = (k - 1) * GUTTER
    r_card_height = (available_height - total_r_gutters) / k

    for idx, (sec_title, sec_desc) in enumerate(sec_blocks_display):
        r_top = content_top + idx * (r_card_height + GUTTER)
        rcard = _render_card(
            slide,
            right_left,
            r_top,
            right_width,
            r_card_height,
            bg_color=SURFACE_ELEVATED,
            border_color=BORDER,
        )
        rtf = rcard.text_frame
        rtf.word_wrap = True
        rtf.margin_left = Inches(0.28)
        rtf.margin_top = Inches(0.22)
        rtf.margin_right = Inches(0.28)
        rtf.margin_bottom = Inches(0.22)

        # Title of thesis
        rp_title = rtf.paragraphs[0]
        rp_title.text = sec_title
        rp_title.font.name = FONT_FAMILY
        rp_title.font.size = Pt(16)
        rp_title.font.bold = True
        rp_title.font.color.rgb = TEXT_PRIMARY
        rp_title.space_after = Pt(4)

        # Description of thesis
        if sec_desc:
            rp_desc = rtf.add_paragraph()
            rp_desc.text = sec_desc
            rp_desc.font.name = FONT_FAMILY
            rp_desc.font.size = Pt(13)
            rp_desc.font.color.rgb = TEXT_SECONDARY


def _render_definitions_slide(
    slide,
    deck: NBDeck,
    slide_data: NBSlide,
    college_color: RGBColor,
) -> None:
    """Render a NotebookLM-style definitions slide with accent-chip term cards."""
    # Header
    title = slide_data.title or "Ключевые термины"
    subtitle = slide_data.subtitle or "Основные понятия и определения дисциплины"
    _render_header(slide, title=title, subtitle=subtitle, tag="ГЛОССАРИЙ", accent_color=college_color)

    available_width = SLIDE_WIDTH - (MARGIN * 2)
    content_top = Inches(1.6)
    footer_margin = Inches(0.55)
    max_bottom = SLIDE_HEIGHT - MARGIN - footer_margin
    available_height = max_bottom - content_top

    # Extract terms with fallback to sections or items
    raw_terms: list[tuple[str, str]] = []
    if slide_data.terms:
        for term, defn in slide_data.terms:
            t = str(term).strip()
            d = str(defn).strip()
            if t or d:
                raw_terms.append((t or "Термин", d))
    elif slide_data.sections:
        for heading, body in slide_data.sections:
            h = str(heading).strip()
            b = str(body).strip()
            if h or b:
                clean_h = re.sub(r"^\d+[\.\)]\s*", "", h)
                raw_terms.append((clean_h or "Термин", b))
    elif slide_data.items:
        for it in slide_data.items:
            it_str = str(it).strip()
            if " - " in it_str:
                t, d = it_str.split(" - ", 1)
            elif " — " in it_str:
                t, d = it_str.split(" — ", 1)
            elif ": " in it_str:
                t, d = it_str.split(": ", 1)
            else:
                t, d = "Термин", it_str
            clean_t = re.sub(r"^\d+[\.\)]\s*", "", t.strip())
            raw_terms.append((clean_t or "Термин", d.strip()))

    if not raw_terms:
        raw_terms = [
            ("Понятие 1", "Базовое определение термина в контексте изучаемой темы."),
            ("Понятие 2", "Специализированное определение с описанием сферы применения."),
            ("Понятие 3", "Связанный термин, расширяющий понимание темы занятия."),
        ]

    # Display 2 to 3 term cards
    display_terms = raw_terms[:3]
    k = max(1, len(display_terms))

    # Highlight box at bottom if present
    has_highlight = bool(slide_data.highlight and slide_data.highlight.strip())
    if has_highlight:
        hl_height = Inches(0.95)
        hl_top = max_bottom - hl_height
        _render_highlight_box(
            slide,
            MARGIN,
            hl_top,
            available_width,
            hl_height,
            slide_data.highlight,
            title="ГЛАВНЫЙ ВЫВОД",
            accent_color=college_color,
        )
        cards_area_height = hl_top - GUTTER - content_top
    else:
        cards_area_height = available_height

    total_gutters = (k - 1) * GUTTER
    card_width = (available_width - total_gutters) / k

    for i, (term, defn) in enumerate(display_terms):
        c_left = MARGIN + i * (card_width + GUTTER)
        _render_card(
            slide,
            c_left,
            content_top,
            card_width,
            cards_area_height,
            bg_color=CARD,
            border_color=BORDER,
        )

        # Term accent chip
        chip_left = c_left + Inches(0.28)
        chip_top = content_top + Inches(0.25)
        chip_height = Inches(0.44)
        estimated_w = Inches(0.5) + Pt(len(term) * 9.5)
        chip_width = min(card_width - Inches(0.56), max(Inches(1.5), estimated_w))

        chip = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE, chip_left, chip_top, chip_width, chip_height
        )
        chip.fill.solid()
        chip.fill.fore_color.rgb = college_color
        chip.line.fill.background()

        ctf = chip.text_frame
        ctf.word_wrap = True
        ctf.margin_left = Inches(0.14)
        ctf.margin_right = Inches(0.14)
        ctf.margin_top = Inches(0.08)
        ctf.margin_bottom = Inches(0.08)
        cp = ctf.paragraphs[0]
        cp.text = term
        cp.font.name = FONT_FAMILY
        cp.font.size = Pt(11) if len(term) > 22 else Pt(13)
        cp.font.bold = True
        cp.font.color.rgb = TEXT_PRIMARY

        # Definition text box under the term chip
        def_top = chip_top + chip_height + Inches(0.18)
        def_left = c_left + Inches(0.28)
        def_width = card_width - Inches(0.56)
        def_height = cards_area_height - (def_top - content_top) - Inches(0.18)

        def_box = slide.shapes.add_textbox(def_left, def_top, def_width, def_height)
        dtf = def_box.text_frame
        dtf.word_wrap = True
        dtf.margin_left = Inches(0)
        dtf.margin_right = Inches(0)
        dtf.margin_top = Inches(0)
        dtf.margin_bottom = Inches(0)
        dp = dtf.paragraphs[0]
        dp.text = defn
        dp.font.name = FONT_FAMILY
        dp.font.size = Pt(15)
        dp.font.color.rgb = TEXT_SECONDARY


def _render_process_slide(
    slide,
    deck: NBDeck,
    slide_data: NBSlide,
    college_color: RGBColor,
) -> None:
    """Render a NotebookLM-style horizontal process/timeline slide."""
    # Header
    title = slide_data.title or "Процесс и этапы"
    subtitle = slide_data.subtitle or "Последовательность выполнения и ключевые фазы"
    _render_header(slide, title=title, subtitle=subtitle, tag="ПРОЦЕСС", accent_color=college_color)

    available_width = SLIDE_WIDTH - (MARGIN * 2)
    content_top = Inches(1.6)
    footer_margin = Inches(0.55)
    max_bottom = SLIDE_HEIGHT - MARGIN - footer_margin
    available_height = max_bottom - content_top

    # Extract steps with fallback to timeline, sections, or items
    raw_steps: list[tuple[str, str]] = []
    if slide_data.steps:
        for heading, body in slide_data.steps:
            h = str(heading).strip()
            b = str(body).strip()
            if h or b:
                raw_steps.append((re.sub(r"^\d+[\.\)]\s*", "", h) or "Этап", b))
    elif slide_data.timeline:
        for stage, desc in slide_data.timeline:
            s = str(stage).strip()
            d = str(desc).strip()
            if s or d:
                raw_steps.append((re.sub(r"^\d+[\.\)]\s*", "", s) or "Этап", d))
    elif slide_data.sections:
        for heading, body in slide_data.sections:
            h = str(heading).strip()
            b = str(body).strip()
            if h or b:
                raw_steps.append((re.sub(r"^\d+[\.\)]\s*", "", h) or "Этап", b))
    elif slide_data.items:
        for it in slide_data.items:
            it_str = str(it).strip()
            if " - " in it_str:
                h, b = it_str.split(" - ", 1)
            elif " — " in it_str:
                h, b = it_str.split(" — ", 1)
            elif ": " in it_str:
                h, b = it_str.split(": ", 1)
            else:
                h, b = "Этап", it_str
            clean_h = re.sub(r"^\d+[\.\)]\s*", "", h.strip())
            raw_steps.append((clean_h or "Этап", b.strip()))

    if not raw_steps:
        raw_steps = [
            ("Инициализация", "Подготовка исходных данных и окружения."),
            ("Проектирование", "Определение архитектуры и спецификаций."),
            ("Реализация", "Разработка и сборка основных компонентов."),
            ("Верификация", "Тестирование и контроль соответствия требованиям."),
        ]

    # Clamp to 1–5 steps horizontally without creating empty cards
    display_steps = raw_steps[:5]
    n = max(1, len(display_steps))

    # Adaptive typography and padding based on step count
    if n <= 3:
        title_font_size = Pt(17)
        desc_font_size = Pt(13.5)
        padding = Inches(0.28)
    elif n == 4:
        title_font_size = Pt(15)
        desc_font_size = Pt(12.5)
        padding = Inches(0.22)
    else:  # 5 steps
        title_font_size = Pt(13.5)
        desc_font_size = Pt(11.0)
        padding = Inches(0.18)

    # Highlight box at bottom if present
    has_highlight = bool(slide_data.highlight and slide_data.highlight.strip())
    if has_highlight:
        hl_height = Inches(0.95)
        hl_top = max_bottom - hl_height
        _render_highlight_box(
            slide,
            MARGIN,
            hl_top,
            available_width,
            hl_height,
            slide_data.highlight,
            title="ВАЖНЫЙ РЕЗУЛЬТАТ",
            accent_color=college_color,
        )
        process_area_height = hl_top - GUTTER - content_top
    else:
        process_area_height = available_height

    total_gutters = (n - 1) * GUTTER
    step_width = (available_width - total_gutters) / n

    for i, (st_title, st_desc) in enumerate(display_steps):
        c_left = MARGIN + i * (step_width + GUTTER)
        _render_card(
            slide,
            c_left,
            content_top,
            step_width,
            process_area_height,
            bg_color=CARD,
            border_color=BORDER,
        )

        # Numbered circular marker with accent_for(i) formatted as 01, 02, 03...
        marker_size = Inches(0.56)
        marker_left = c_left + padding
        marker_top = content_top + Inches(0.25)
        marker = slide.shapes.add_shape(
            MSO_SHAPE.OVAL, marker_left, marker_top, marker_size, marker_size
        )
        marker.fill.solid()
        marker.fill.fore_color.rgb = accent_for(i)
        marker.line.fill.background()

        mtf = marker.text_frame
        mtf.word_wrap = False
        mtf.margin_left = Inches(0)
        mtf.margin_right = Inches(0)
        mtf.margin_top = Inches(0.09)
        mtf.margin_bottom = Inches(0)
        mp = mtf.paragraphs[0]
        mp.text = f"{i + 1:02d}"
        mp.font.name = FONT_FAMILY
        mp.font.size = Pt(13)
        mp.font.bold = True
        mp.font.color.rgb = TEXT_PRIMARY
        mp.alignment = PP_ALIGN.CENTER

        # Visual connector arrow to next step
        if i < n - 1:
            arrow_left = c_left + step_width + Pt(3)
            arrow_top = marker_top + marker_size / 2 - Pt(4)
            arrow_w = GUTTER - Pt(6)
            arrow = slide.shapes.add_shape(
                MSO_SHAPE.RIGHT_ARROW, arrow_left, arrow_top, arrow_w, Pt(8)
            )
            arrow.fill.solid()
            arrow.fill.fore_color.rgb = DIVIDER
            arrow.line.fill.background()

        # Step title and description text
        text_top = marker_top + marker_size + Inches(0.18)
        text_left = c_left + padding
        text_width = step_width - (padding * 2)
        text_height = process_area_height - (text_top - content_top) - Inches(0.18)

        t_box = slide.shapes.add_textbox(text_left, text_top, text_width, text_height)
        ttf = t_box.text_frame
        ttf.word_wrap = True
        ttf.margin_left = Inches(0)
        ttf.margin_right = Inches(0)
        ttf.margin_top = Inches(0)
        ttf.margin_bottom = Inches(0)

        tp_title = ttf.paragraphs[0]
        tp_title.text = st_title
        tp_title.font.name = FONT_FAMILY
        tp_title.font.size = title_font_size
        tp_title.font.bold = True
        tp_title.font.color.rgb = TEXT_PRIMARY
        tp_title.space_after = Pt(5)

        if st_desc:
            tp_desc = ttf.add_paragraph()
            tp_desc.text = st_desc
            tp_desc.font.name = FONT_FAMILY
            tp_desc.font.size = desc_font_size
            tp_desc.font.color.rgb = TEXT_SECONDARY


def _render_compare_slide(
    slide,
    deck: NBDeck,
    slide_data: NBSlide,
    college_color: RGBColor,
) -> None:
    """Render a NotebookLM-style comparison slide with 2–3 structured columns."""
    # Header
    title = slide_data.title or "Сравнительный анализ"
    subtitle = slide_data.subtitle or "Сопоставление подходов, характеристик и сценариев"
    _render_header(slide, title=title, subtitle=subtitle, tag="СРАВНЕНИЕ", accent_color=college_color)

    available_width = SLIDE_WIDTH - (MARGIN * 2)
    content_top = Inches(1.6)
    footer_margin = Inches(0.55)
    max_bottom = SLIDE_HEIGHT - MARGIN - footer_margin
    available_height = max_bottom - content_top

    # Extract comparisons with fallback to sections or items
    raw_comparisons: list[tuple[str, list[str]]] = []
    if slide_data.comparisons:
        for label, values in slide_data.comparisons:
            lbl = str(label).strip()
            pts = [str(v).strip() for v in values if str(v).strip()]
            if lbl or pts:
                raw_comparisons.append((lbl or "Вариант", pts))
    elif slide_data.sections:
        for section in slide_data.sections:
            lines = [ln.strip() for ln in str(section).split("\n") if ln.strip()]
            h = lines[0] if lines else "Категория"
            pts = [ln.lstrip("•-*0123456789. ") for ln in lines[1:]] or ["Ключевая характеристика"]
            raw_comparisons.append((h, pts))
    elif slide_data.items:
        items_list = [str(it).strip() for it in slide_data.items if str(it).strip()]
        mid = (len(items_list) + 1) // 2
        col1 = items_list[:mid] or ["Характеристика подхода"]
        col2 = items_list[mid:] or ["Альтернативная характеристика"]
        raw_comparisons.append(("Вариант A", col1))
        raw_comparisons.append(("Вариант B", col2))

    if not raw_comparisons:
        raw_comparisons = [
            ("Подход 1", ["Основная концепция решения", "Ключевые преимущества", "Сценарий применения"]),
            ("Подход 2", ["Альтернативная концепция", "Специфика реализации", "Условия применимости"]),
        ]

    # Limit to 2 or 3 columns
    display_cols = raw_comparisons[:3]
    n = max(1, len(display_cols))

    # Highlight box at bottom if present
    has_highlight = bool(slide_data.highlight and slide_data.highlight.strip())
    if has_highlight:
        hl_height = Inches(0.95)
        hl_top = max_bottom - hl_height
        _render_highlight_box(
            slide,
            MARGIN,
            hl_top,
            available_width,
            hl_height,
            slide_data.highlight,
            title="ИТОГ СРАВНЕНИЯ",
            accent_color=college_color,
        )
        compare_area_height = hl_top - GUTTER - content_top
    else:
        compare_area_height = available_height

    total_gutters = (n - 1) * GUTTER
    col_width = (available_width - total_gutters) / n

    for i, (col_title, col_points) in enumerate(display_cols):
        c_left = MARGIN + i * (col_width + GUTTER)
        col_accent = accent_for(i)

        _render_card(
            slide,
            c_left,
            content_top,
            col_width,
            compare_area_height,
            bg_color=CARD,
            border_color=BORDER,
        )

        # Accent stripe across the top of column
        stripe = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            c_left + Inches(0.25),
            content_top + Inches(0.22),
            Inches(1.2),
            Pt(4),
        )
        stripe.fill.solid()
        stripe.fill.fore_color.rgb = col_accent
        stripe.line.fill.background()

        # Column title
        title_box = slide.shapes.add_textbox(
            c_left + Inches(0.25),
            content_top + Inches(0.32),
            col_width - Inches(0.5),
            Inches(0.5),
        )
        ttf = title_box.text_frame
        ttf.word_wrap = True
        ttf.margin_left = Inches(0)
        ttf.margin_right = Inches(0)
        ttf.margin_top = Inches(0)
        ttf.margin_bottom = Inches(0)
        tp = ttf.paragraphs[0]
        tp.text = col_title
        tp.font.name = FONT_FAMILY
        tp.font.size = Pt(18)
        tp.font.bold = True
        tp.font.color.rgb = TEXT_PRIMARY

        # Divider under title
        div = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            c_left + Inches(0.25),
            content_top + Inches(0.85),
            col_width - Inches(0.5),
            Pt(1),
        )
        div.fill.solid()
        div.fill.fore_color.rgb = DIVIDER
        div.line.fill.background()

        # Structured bullet points
        points_top = content_top + Inches(0.95)
        points_height = compare_area_height - (points_top - content_top) - Inches(0.15)
        p_box = slide.shapes.add_textbox(
            c_left + Inches(0.25), points_top, col_width - Inches(0.5), points_height
        )
        ptf = p_box.text_frame
        ptf.word_wrap = True
        ptf.margin_left = Inches(0)
        ptf.margin_right = Inches(0)
        ptf.margin_top = Inches(0)
        ptf.margin_bottom = Inches(0)

        for pt_idx, pt in enumerate(col_points):
            p = ptf.paragraphs[0] if pt_idx == 0 else ptf.add_paragraph()
            p.space_after = Pt(8)

            # Bullet run in distinct accent color
            r_bullet = p.add_run()
            r_bullet.text = "•  "
            r_bullet.font.name = FONT_FAMILY
            r_bullet.font.size = Pt(14)
            r_bullet.font.bold = True
            r_bullet.font.color.rgb = col_accent

            # Text run in secondary color
            r_text = p.add_run()
            r_text.text = str(pt)
            r_text.font.name = FONT_FAMILY
            r_text.font.size = Pt(14)
            r_text.font.color.rgb = TEXT_SECONDARY


def _render_stats_slide(
    slide,
    deck: NBDeck,
    slide_data: NBSlide,
    college_color: RGBColor,
) -> None:
    """Render a NotebookLM-style KPI/stats slide with large number cards."""
    title = slide_data.title or "Статистика"
    subtitle = slide_data.subtitle or "Ключевые показатели и метрики"
    _render_header(slide, title=title, subtitle=subtitle, tag="СТАТИСТИКА", accent_color=college_color)

    available_width = SLIDE_WIDTH - (MARGIN * 2)
    content_top = Inches(1.65)
    footer_margin = Inches(0.55)
    highlight_h = Inches(0.75)

    # ── Gather KPI items: (value, label, description?) ────────────────────────
    kpis: list[tuple[str, str, str]] = []  # (value, label, description)

    if slide_data.statistics:
        # statistics: tuple[tuple[str, str], ...] → (value, label)
        for item in slide_data.statistics:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                val = str(item[0]).strip()
                lbl = str(item[1]).strip()
                desc = str(item[2]).strip() if len(item) > 2 else ""
                if val or lbl:
                    kpis.append((val or "—", lbl or "Показатель", desc))
    elif slide_data.sections:
        # sections: tuple[tuple[str, str], ...] → (heading, body)
        for sec in slide_data.sections:
            if isinstance(sec, (tuple, list)) and len(sec) >= 2:
                heading = str(sec[0]).strip()
                body = str(sec[1]).strip()
                kpis.append((heading, body, ""))
            else:
                # plain string section
                lines = [ln.strip() for ln in str(sec).split("\n") if ln.strip()]
                val = lines[0] if lines else "—"
                lbl = lines[1] if len(lines) > 1 else "Показатель"
                desc = lines[2] if len(lines) > 2 else ""
                kpis.append((val, lbl, desc))
    elif slide_data.items:
        # Treat pairs of items as (value, label); odd item becomes its own card
        items_list = [str(it).strip() for it in slide_data.items if str(it).strip()]
        it = iter(items_list)
        for val in it:
            lbl = next(it, "Показатель")
            kpis.append((val, lbl, ""))

    # Limit to 4 cards
    kpis = kpis[:4]

    has_highlight = bool(slide_data.highlight)
    if has_highlight:
        highlight_top = SLIDE_HEIGHT - MARGIN - footer_margin - highlight_h
        max_bottom = highlight_top - GUTTER
    else:
        max_bottom = SLIDE_HEIGHT - MARGIN - footer_margin

    content_height = max_bottom - content_top
    n = max(1, len(kpis))

    # ── Layout: adaptive width per count ──────────────────────────────────────
    if n <= 2:
        card_w = (available_width - GUTTER * (n - 1)) / n
        card_h = min(content_height, Inches(3.6))
    else:
        card_w = (available_width - GUTTER * (n - 1)) / n
        card_h = min(content_height, Inches(3.2))

    card_top = content_top + (content_height - card_h) / 2

    for i, (val, lbl, desc) in enumerate(kpis):
        card_left = MARGIN + i * (card_w + GUTTER)
        accent = accent_for(i)

        # Card background
        _render_card(slide, card_left, card_top, card_w, card_h, bg_color=CARD, border_color=BORDER)

        # Accent top stripe
        stripe_h = Inches(0.06)
        stripe = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            card_left, card_top, card_w, stripe_h,
        )
        stripe.line.fill.background()
        stripe.fill.solid()
        stripe.fill.fore_color.rgb = accent

        inner_pad = Inches(0.28)

        # Big numeric value
        val_h = Inches(1.2)
        val_top = card_top + stripe_h + inner_pad
        val_box = slide.shapes.add_textbox(
            card_left + inner_pad,
            val_top,
            card_w - inner_pad * 2,
            val_h,
        )
        vtf = val_box.text_frame
        vtf.word_wrap = False
        vp = vtf.paragraphs[0]
        vp.alignment = PP_ALIGN.CENTER
        vr = vp.add_run()
        vr.text = val
        vr.font.name = FONT_FAMILY
        vr.font.size = Pt(42) if n <= 2 else Pt(34)
        vr.font.bold = True
        vr.font.color.rgb = college_color

        # Label
        lbl_top = val_top + val_h + Inches(0.05)
        lbl_h = Inches(0.55)
        lbl_box = slide.shapes.add_textbox(
            card_left + inner_pad,
            lbl_top,
            card_w - inner_pad * 2,
            lbl_h,
        )
        ltf = lbl_box.text_frame
        ltf.word_wrap = True
        lp = ltf.paragraphs[0]
        lp.alignment = PP_ALIGN.CENTER
        lr = lp.add_run()
        lr.text = lbl
        lr.font.name = FONT_FAMILY
        lr.font.size = Pt(16) if n <= 2 else Pt(13)
        lr.font.bold = True
        lr.font.color.rgb = TEXT_PRIMARY

        # Optional description
        if desc:
            desc_top = lbl_top + lbl_h + Inches(0.05)
            desc_remaining = card_top + card_h - desc_top - Inches(0.1)
            if desc_remaining > Inches(0.3):
                desc_box = slide.shapes.add_textbox(
                    card_left + inner_pad,
                    desc_top,
                    card_w - inner_pad * 2,
                    desc_remaining,
                )
                dtf = desc_box.text_frame
                dtf.word_wrap = True
                dp = dtf.paragraphs[0]
                dp.alignment = PP_ALIGN.CENTER
                dr = dp.add_run()
                dr.text = desc
                dr.font.name = FONT_FAMILY
                dr.font.size = Pt(12)
                dr.font.color.rgb = TEXT_MUTED

        # Bottom accent line (decorative)
        div = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            card_left + inner_pad,
            card_top + card_h - Inches(0.04),
            card_w - inner_pad * 2,
            Inches(0.02),
        )
        div.line.fill.background()
        div.fill.solid()
        div.fill.fore_color.rgb = accent

    # ── Highlight box ──────────────────────────────────────────────────────────
    if has_highlight:
        _render_highlight_box(
            slide,
            left=MARGIN,
            top=highlight_top,
            width=available_width,
            height=highlight_h,
            text=slide_data.highlight,
            title="ВЫВОД",
            accent_color=college_color,
            bg_color=SURFACE_ELEVATED,
        )

    # ── Placeholder when no data ───────────────────────────────────────────────
    if not kpis:
        ph_box = slide.shapes.add_textbox(
            MARGIN, content_top, available_width, Inches(1.0)
        )
        ph_p = ph_box.text_frame.paragraphs[0]
        ph_p.alignment = PP_ALIGN.CENTER
        ph_r = ph_p.add_run()
        ph_r.text = "Данные статистики не указаны"
        ph_r.font.name = FONT_FAMILY
        ph_r.font.size = BODY_SIZE
        ph_r.font.color.rgb = TEXT_MUTED


def _render_cases_slide(
    slide,
    deck: NBDeck,
    slide_data: NBSlide,
    college_color: RGBColor,
) -> None:
    """Render a NotebookLM-style case-study slide with structured case cards."""
    title = slide_data.title or "Практические кейсы"
    subtitle = slide_data.subtitle or "Реальные сценарии применения"
    _render_header(slide, title=title, subtitle=subtitle, tag="КЕЙСЫ", accent_color=college_color)

    available_width = SLIDE_WIDTH - (MARGIN * 2)
    content_top = Inches(1.65)
    footer_margin = Inches(0.55)
    highlight_h = Inches(0.75)

    # ── Gather cases: list of (name, description, solution) ───────────────────
    # Primary source: sections → tuple[tuple[str, str], ...] = (name, body)
    # Body may contain multiline text; we split on "\n" to get description/solution.
    # Fallback: items → treat every two items as (name, description).
    cases: list[tuple[str, str, str]] = []  # (name, description, solution)

    if slide_data.sections:
        for sec in slide_data.sections:
            if isinstance(sec, (tuple, list)) and len(sec) >= 2:
                name = str(sec[0]).strip()
                body = str(sec[1]).strip()
            else:
                # plain string
                lines = [ln.strip() for ln in str(sec).split("\n") if ln.strip()]
                name = lines[0] if lines else "Кейс"
                body = "\n".join(lines[1:]) if len(lines) > 1 else ""
            # Split body into description (first paragraph) and solution (rest)
            body_lines = [ln for ln in body.split("\n") if ln.strip()]
            desc = body_lines[0] if body_lines else ""
            solution = " ".join(body_lines[1:]) if len(body_lines) > 1 else ""
            cases.append((name or "Кейс", desc, solution))
    elif slide_data.items:
        items_list = [str(it).strip() for it in slide_data.items if str(it).strip()]
        it = iter(items_list)
        for name in it:
            desc = next(it, "")
            cases.append((name, desc, ""))

    # Limit to 3 — beyond that readability suffers
    cases = cases[:3]

    has_highlight = bool(slide_data.highlight)
    if has_highlight:
        highlight_top = SLIDE_HEIGHT - MARGIN - footer_margin - highlight_h
        max_bottom = highlight_top - GUTTER
    else:
        max_bottom = SLIDE_HEIGHT - MARGIN - footer_margin

    content_height = max_bottom - content_top
    n = max(1, len(cases))

    card_w = (available_width - GUTTER * (n - 1)) / n
    card_h = content_height  # fill full available height

    for i, (name, desc, solution) in enumerate(cases):
        card_left = MARGIN + i * (card_w + GUTTER)
        accent = accent_for(i)

        # ── Card background ────────────────────────────────────────────────────
        _render_card(slide, card_left, content_top, card_w, card_h,
                     bg_color=CARD, border_color=BORDER)

        inner_pad = Inches(0.25)
        cur_y = content_top + inner_pad

        # ── Case number badge ──────────────────────────────────────────────────
        badge_size = Inches(0.42)
        badge = slide.shapes.add_shape(
            MSO_SHAPE.OVAL,
            card_left + inner_pad,
            cur_y,
            badge_size,
            badge_size,
        )
        badge.fill.solid()
        badge.fill.fore_color.rgb = accent
        badge.line.fill.background()
        btf = badge.text_frame
        btf.margin_left = Inches(0)
        btf.margin_right = Inches(0)
        btf.margin_top = Inches(0)
        btf.margin_bottom = Inches(0)
        bp = btf.paragraphs[0]
        bp.alignment = PP_ALIGN.CENTER
        br = bp.add_run()
        br.text = f"{i + 1:02d}"
        br.font.name = FONT_FAMILY
        br.font.size = Pt(14)
        br.font.bold = True
        br.font.color.rgb = TEXT_PRIMARY

        # ── Case name (right of badge) ─────────────────────────────────────────
        name_left = card_left + inner_pad + badge_size + Inches(0.15)
        name_w = card_w - inner_pad - badge_size - Inches(0.15) - inner_pad
        name_h = badge_size
        name_box = slide.shapes.add_textbox(name_left, cur_y, name_w, name_h)
        ntf = name_box.text_frame
        ntf.word_wrap = True
        ntf.margin_top = Inches(0)
        ntf.margin_bottom = Inches(0)
        np_ = ntf.paragraphs[0]
        np_.alignment = PP_ALIGN.LEFT
        nr = np_.add_run()
        nr.text = name
        nr.font.name = FONT_FAMILY
        nr.font.size = Pt(15) if n <= 2 else Pt(13)
        nr.font.bold = True
        nr.font.color.rgb = TEXT_PRIMARY

        cur_y += badge_size + Inches(0.18)

        # ── Thin accent divider ────────────────────────────────────────────────
        div_w = card_w - inner_pad * 2
        div = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            card_left + inner_pad,
            cur_y,
            div_w,
            Inches(0.025),
        )
        div.fill.solid()
        div.fill.fore_color.rgb = accent
        div.line.fill.background()

        cur_y += Inches(0.025) + Inches(0.15)

        # ── Description label + text ───────────────────────────────────────────
        remaining_h = content_top + card_h - cur_y - inner_pad
        # Split height between description and solution
        has_solution = bool(solution)
        if has_solution:
            desc_h = remaining_h * 0.52
            sol_h = remaining_h * 0.42
        else:
            desc_h = remaining_h
            sol_h = Inches(0)

        if desc:
            # "СИТУАЦИЯ" micro-label
            lbl_h = Inches(0.22)
            lbl_box = slide.shapes.add_textbox(
                card_left + inner_pad, cur_y,
                card_w - inner_pad * 2, lbl_h,
            )
            lp_ = lbl_box.text_frame.paragraphs[0]
            lr_ = lp_.add_run()
            lr_.text = "СИТУАЦИЯ"
            lr_.font.name = FONT_FAMILY
            lr_.font.size = Pt(9)
            lr_.font.bold = True
            lr_.font.color.rgb = accent
            cur_y += lbl_h

            desc_box = slide.shapes.add_textbox(
                card_left + inner_pad, cur_y,
                card_w - inner_pad * 2, desc_h - lbl_h,
            )
            dtf = desc_box.text_frame
            dtf.word_wrap = True
            dtf.margin_top = Inches(0)
            dp_ = dtf.paragraphs[0]
            dr_ = dp_.add_run()
            dr_.text = desc
            dr_.font.name = FONT_FAMILY
            dr_.font.size = Pt(13) if n <= 2 else Pt(11)
            dr_.font.color.rgb = TEXT_SECONDARY
            cur_y += desc_h - lbl_h + Inches(0.1)

        # ── Solution block ─────────────────────────────────────────────────────
        if has_solution and sol_h > Inches(0.3):
            # "РЕШЕНИЕ" micro-label
            sol_lbl_h = Inches(0.22)
            sol_lbl = slide.shapes.add_textbox(
                card_left + inner_pad, cur_y,
                card_w - inner_pad * 2, sol_lbl_h,
            )
            slp = sol_lbl.text_frame.paragraphs[0]
            slr = slp.add_run()
            slr.text = "РЕШЕНИЕ"
            slr.font.name = FONT_FAMILY
            slr.font.size = Pt(9)
            slr.font.bold = True
            slr.font.color.rgb = college_color
            cur_y += sol_lbl_h

            sol_box = slide.shapes.add_textbox(
                card_left + inner_pad, cur_y,
                card_w - inner_pad * 2, sol_h - sol_lbl_h,
            )
            stf = sol_box.text_frame
            stf.word_wrap = True
            stf.margin_top = Inches(0)
            sp_ = stf.paragraphs[0]
            sr_ = sp_.add_run()
            sr_.text = solution
            sr_.font.name = FONT_FAMILY
            sr_.font.size = Pt(12) if n <= 2 else Pt(10)
            sr_.font.color.rgb = TEXT_SECONDARY

        # ── Bottom accent stripe ───────────────────────────────────────────────
        bot_y = content_top + card_h - Inches(0.04)
        bot = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            card_left + inner_pad,
            bot_y,
            div_w,
            Inches(0.02),
        )
        bot.fill.solid()
        bot.fill.fore_color.rgb = accent
        bot.line.fill.background()

    # ── Highlight box ──────────────────────────────────────────────────────────
    if has_highlight:
        _render_highlight_box(
            slide,
            left=MARGIN,
            top=highlight_top,
            width=available_width,
            height=highlight_h,
            text=slide_data.highlight,
            title="ВЫВОД",
            accent_color=college_color,
            bg_color=SURFACE_ELEVATED,
        )

    # ── Placeholder when no data ───────────────────────────────────────────────
    if not cases:
        ph_box = slide.shapes.add_textbox(
            MARGIN, content_top, available_width, Inches(1.0)
        )
        ph_p = ph_box.text_frame.paragraphs[0]
        ph_p.alignment = PP_ALIGN.CENTER
        ph_r = ph_p.add_run()
        ph_r.text = "Практические кейсы не указаны"
        ph_r.font.name = FONT_FAMILY
        ph_r.font.size = BODY_SIZE
        ph_r.font.color.rgb = TEXT_MUTED


def _render_fallback_slide(
    slide,
    deck: NBDeck,
    slide_data: NBSlide,
    college_color: RGBColor,
) -> None:
    """Render a generic content slide for slide kinds that do not have a dedicated renderer yet."""
    _render_header(
        slide,
        title=slide_data.title or deck.title,
        subtitle=slide_data.subtitle,
        tag=slide_data.kind.upper(),
        accent_color=college_color,
    )

    card_width = SLIDE_WIDTH - (MARGIN * 2)
    content_top = Inches(1.8)
    content_height = SLIDE_HEIGHT - content_top - MARGIN - Inches(0.6)

    card = _render_card(
        slide,
        MARGIN,
        content_top,
        card_width,
        content_height,
        bg_color=CARD,
        border_color=BORDER,
    )
    tf = card.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.3)
    tf.margin_top = Inches(0.3)
    tf.margin_right = Inches(0.3)
    tf.margin_bottom = Inches(0.3)

    p_first = tf.paragraphs[0]
    has_content = False

    if slide_data.items:
        for i, item in enumerate(slide_data.items):
            p = p_first if i == 0 else tf.add_paragraph()
            p.text = f"•  {item}"
            p.font.name = FONT_FAMILY
            p.font.size = BODY_SIZE
            p.font.color.rgb = TEXT_SECONDARY
            p.space_after = Pt(8)
        has_content = True
    elif slide_data.sections:
        for i, (sec_title, sec_body) in enumerate(slide_data.sections):
            p1 = p_first if i == 0 else tf.add_paragraph()
            p1.text = sec_title
            p1.font.name = FONT_FAMILY
            p1.font.size = Pt(18)
            p1.font.bold = True
            p1.font.color.rgb = TEXT_PRIMARY
            p1.space_after = Pt(4)

            p2 = tf.add_paragraph()
            p2.text = sec_body
            p2.font.name = FONT_FAMILY
            p2.font.size = Pt(16)
            p2.font.color.rgb = TEXT_SECONDARY
            p2.space_after = Pt(10)
        has_content = True
    elif slide_data.terms:
        for i, (term, defn) in enumerate(slide_data.terms):
            p1 = p_first if i == 0 else tf.add_paragraph()
            p1.text = term
            p1.font.name = FONT_FAMILY
            p1.font.size = Pt(18)
            p1.font.bold = True
            p1.font.color.rgb = college_color
            p1.space_after = Pt(2)

            p2 = tf.add_paragraph()
            p2.text = defn
            p2.font.name = FONT_FAMILY
            p2.font.size = Pt(16)
            p2.font.color.rgb = TEXT_SECONDARY
            p2.space_after = Pt(10)
        has_content = True
    elif slide_data.code:
        p_first.text = slide_data.code
        p_first.font.name = "Menlo"
        p_first.font.size = Pt(15)
        p_first.font.color.rgb = TEXT_PRIMARY
        has_content = True

    if slide_data.highlight:
        p_hl = tf.add_paragraph() if has_content else p_first
        p_hl.text = f"Важно: {slide_data.highlight}"
        p_hl.font.name = FONT_FAMILY
        p_hl.font.size = Pt(16)
        p_hl.font.bold = True
        p_hl.font.color.rgb = college_color
        p_hl.space_before = Pt(12)
        has_content = True

    if not has_content:
        p_first.text = "Содержимое слайда формируется..."
        p_first.font.name = FONT_FAMILY
        p_first.font.size = BODY_SIZE
        p_first.font.color.rgb = TEXT_MUTED


def render_nb_deck(deck: NBDeck) -> BytesIO:
    """Render an NBDeck presentation into a PPTX BytesIO buffer."""
    prs = _init_presentation()
    college_color = college_accent(deck.college)
    total_slides = len(deck.slides)

    for idx, slide_data in enumerate(deck.slides, start=1):
        slide = _create_slide(prs)
        if slide_data.kind == "title":
            _render_title_slide(slide, deck, slide_data, college_color)
        elif slide_data.kind == "overview":
            _render_overview_slide(slide, deck, slide_data, college_color)
            _render_footer(
                slide,
                text=f"{deck.subject} • {deck.college}" if deck.subject else deck.college,
                slide_index=idx,
                total_slides=total_slides,
            )
        elif slide_data.kind == "concept":
            _render_concept_slide(slide, deck, slide_data, college_color)
            _render_footer(
                slide,
                text=f"{deck.subject} • {deck.college}" if deck.subject else deck.college,
                slide_index=idx,
                total_slides=total_slides,
            )
        elif slide_data.kind == "definitions":
            _render_definitions_slide(slide, deck, slide_data, college_color)
            _render_footer(
                slide,
                text=f"{deck.subject} • {deck.college}" if deck.subject else deck.college,
                slide_index=idx,
                total_slides=total_slides,
            )
        elif slide_data.kind == "process":
            _render_process_slide(slide, deck, slide_data, college_color)
            _render_footer(
                slide,
                text=f"{deck.subject} • {deck.college}" if deck.subject else deck.college,
                slide_index=idx,
                total_slides=total_slides,
            )
        elif slide_data.kind == "compare":
            _render_compare_slide(slide, deck, slide_data, college_color)
            _render_footer(
                slide,
                text=f"{deck.subject} • {deck.college}" if deck.subject else deck.college,
                slide_index=idx,
                total_slides=total_slides,
            )
        elif slide_data.kind == "stats":
            _render_stats_slide(slide, deck, slide_data, college_color)
            _render_footer(
                slide,
                text=f"{deck.subject} • {deck.college}" if deck.subject else deck.college,
                slide_index=idx,
                total_slides=total_slides,
            )
        else:
            _render_fallback_slide(slide, deck, slide_data, college_color)
            _render_footer(
                slide,
                text=f"{deck.subject} • {deck.college}" if deck.subject else deck.college,
                slide_index=idx,
                total_slides=total_slides,
            )

    file = BytesIO()
    prs.save(file)
    file.seek(0)
    return file


def build_presentation(title: str, slides: Iterable[PresentationSlide]) -> BytesIO:
    """Build a presentation from slides using the dark 16:9 theme."""
    prs = _init_presentation()
    slides_list = list(slides)
    total = len(slides_list) + 1

    # Title slide
    title_slide = _create_slide(prs)
    card_width = SLIDE_WIDTH - (MARGIN * 2)
    card_height = Inches(3.2)
    card_top = (SLIDE_HEIGHT - card_height) / 2
    title_card = _render_card(
        title_slide,
        MARGIN,
        card_top,
        card_width,
        card_height,
        bg_color=CARD,
        border_color=BORDER,
    )
    tf = title_card.text_frame
    p0 = tf.paragraphs[0]
    p0.text = title
    p0.font.name = FONT_FAMILY
    p0.font.size = TITLE_SIZE
    p0.font.bold = True
    p0.font.color.rgb = TEXT_PRIMARY
    _render_footer(title_slide, text=title, slide_index=1, total_slides=total)

    # Content slides
    for idx, slide_data in enumerate(slides_list, start=2):
        slide = _create_slide(prs)
        _render_header(slide, title=slide_data.title)

        content_top = Inches(1.8)
        content_height = SLIDE_HEIGHT - content_top - MARGIN - Inches(0.6)
        content_card = _render_card(
            slide,
            MARGIN,
            content_top,
            card_width,
            content_height,
            bg_color=CARD,
            border_color=BORDER,
        )
        ctf = content_card.text_frame
        cp0 = ctf.paragraphs[0]
        cp0.text = slide_data.content
        cp0.font.name = FONT_FAMILY
        cp0.font.size = BODY_SIZE
        cp0.font.color.rgb = TEXT_SECONDARY

        _render_footer(slide, text=title, slide_index=idx, total_slides=total)

    file = BytesIO()
    prs.save(file)
    file.seek(0)
    return file
