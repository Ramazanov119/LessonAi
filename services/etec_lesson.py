"""Authoritative 90-minute schedule matching the ETEC template's seven intervals."""
import re

ETEC_STAGE_MINUTES = (3, 20, 15, 30, 10, 10, 2)


def fill_etec_timing(doc):
    """Replace printed template times while keeping paragraph/run formatting."""
    for table in doc.tables:
        for row in table.rows:
            if not any('{org_steps}' in cell.text for cell in row.cells):
                continue
            rows = table.rows
            start = next(i for i, candidate in enumerate(rows) if candidate._tr is row._tr)
            intervals = iter(ETEC_STAGE_MINUTES)
            count = 0
            for stage_row in rows[start:start + 6]:
                for paragraph in stage_row.cells[0].paragraphs:
                    matches = list(re.finditer(r'\d+(?=\s*мин\.)', paragraph.text))
                    # Work backwards so text offsets remain valid across split runs.
                    replacements = [(match, str(next(intervals))) for match in matches]
                    for match, value in reversed(replacements):
                        offset = 0
                        for run in paragraph.runs:
                            end = offset + len(run.text)
                            if offset < match.end() and end > match.start():
                                left = max(0, match.start() - offset)
                                right = min(len(run.text), match.end() - offset)
                                run.text = run.text[:left] + (value if offset <= match.start() else '') + run.text[right:]
                            offset = end
                        count += 1
            if count != len(ETEC_STAGE_MINUTES):
                raise ValueError('Шаблон ЕТЭК: не удалось установить расписание на 90 минут.')
            return
    raise ValueError('Шаблон ЕТЭК: не найдена таблица хода занятия.')
