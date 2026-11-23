import re
import unittest
from unittest.mock import patch
from docx import Document
from config.colleges import get_college_config
from services.etec_lesson import ETEC_STAGE_MINUTES, fill_etec_timing


class EtecTimingTests(unittest.TestCase):
    def test_template_has_exactly_90_minutes(self):
        doc = Document(get_college_config('ETEC')['template'])
        fill_etec_timing(doc)
        minutes = []
        for row in doc.tables[1].rows[12:18]:
            minutes.extend(map(int, re.findall(r'(\d+)\s*мин\.', row.cells[0].text)))
        self.assertEqual(tuple(minutes), ETEC_STAGE_MINUTES)
        self.assertEqual(sum(minutes), 90)
        self.assertIn('{org_steps}', doc.tables[1].rows[12].cells[1].text)
        self.assertEqual(get_college_config('ETEC')['lesson_duration'], 90)
        self.assertEqual(get_college_config('META')['lesson_duration'], 70)

    def test_prompt_overrides_old_duration_and_normalizes_response(self):
        from services.ai import create_lesson
        import json
        with patch('services.ai.openai_generate', return_value='{}') as generate:
            result = create_lesson('Math', 'Topic', 'Русский', 'IT', 'Chair',
                                   'Lesson', 70, None, college='etec')
        prompt = generate.call_args.args[0]
        self.assertIn('90 минут', prompt)
        self.assertNotIn('70 минут', prompt)
        payload = json.loads(result)
        self.assertEqual(sum(payload[f'time{i}'] for i in range(1, 8)), 90)
