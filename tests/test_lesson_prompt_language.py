"""Lesson goals must follow the selected language, including Q College."""
import json
import unittest
from unittest.mock import patch

from services.ai import create_lesson


class LessonPromptLanguageTests(unittest.TestCase):
    @patch('services.ai.openai_generate')
    def test_q_goal_instruction_and_example_follow_language(self, provider):
        for language, goal in (
            ('Қазақша', 'Студенттерге циклдерді қолдануды үйрету.'),
            ('Русский', 'Научить студентов применять циклы.'),
            ('English', 'Teach students to apply loops.'),
        ):
            with self.subTest(language=language):
                provider.reset_mock()
                provider.return_value = json.dumps({
                    'goal': goal,
                    'interdisciplinary_connections': 'Mathematics — repeated calculations',
                })
                result = json.loads(create_lesson(
                    'IT', 'Python', language, 'IT', 'Chair', 'Practice', 90, None, college='Q'))
                provider.assert_called_once()
                system = provider.call_args.args[1]
                self.assertNotIn('обязательно начинаться со слова «Научить»', system)
                self.assertNotIn('{goal_example}', system)
                self.assertIn(f'Язык всех текстовых значений JSON: {language}', system)
                example = system.split('Пример цели на языке занятия: ', 1)[1].split('\n', 1)[0]
                if language == 'Қазақша':
                    self.assertIn('үйрету', example)
                    self.assertNotIn('Научить', example)
                    self.assertIn('естественный порядок слов', system)
                elif language == 'Русский':
                    self.assertIn('Научить', example)
                else:
                    self.assertIn('Teach', example)
                self.assertEqual(result['goal'], goal)
