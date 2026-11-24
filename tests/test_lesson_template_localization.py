"""Language selection must apply to every college's fixed DOCX shell."""
from collections import Counter
import re
import unittest
from zipfile import ZipFile

from docx import Document

from config.colleges import COLLEGES
from services.docx_generator import build_doc
from services.etec_lesson import fill_etec_timing
from services.lesson_template_localization import localize_lesson_template
from meta_fixtures import meta_plan


def document_text(doc):
    return '\n'.join(p.text for p in doc.paragraphs) + '\n' + '\n'.join(
        cell.text for table in doc.tables for row in table.rows for cell in row.cells)


def placeholder_counts(doc):
    text = ' '.join(''.join(p.xpath('.//w:t/text()')) for p in doc.element.xpath('.//w:p'))
    return Counter(re.findall(r'\{[^{}]+\}', text))


class LessonTemplateLocalizationTests(unittest.TestCase):
    def test_all_templates_are_single_language_and_preserve_placeholders_and_geometry(self):
        for college, config in COLLEGES.items():
            for language in ('Русский', 'Қазақша'):
                with self.subTest(college=college, language=language):
                    doc = Document(config['template'])
                    if college == 'ETEC':
                        fill_etec_timing(doc)
                    placeholders = placeholder_counts(doc)
                    widths = [[column.width for column in table.columns] for table in doc.tables]
                    drawings = [node.xml for node in doc.element.xpath('.//w:drawing')]
                    sections = [section._sectPr.xml for section in doc.sections]
                    localize_lesson_template(doc, language)
                    self.assertEqual(placeholder_counts(doc), placeholders)
                    self.assertEqual([[c.width for c in t.columns] for t in doc.tables], widths)
                    self.assertEqual([node.xml for node in doc.element.xpath('.//w:drawing')], drawings)
                    self.assertEqual([section._sectPr.xml for section in doc.sections], sections)
                    text = document_text(doc)
                    if language == 'Русский':
                        self.assertNotRegex(text, r'[әғқңөұүһіӘҒҚҢӨҰҮҺІ]')
                        self.assertRegex(text, 'Тема (?:занятия|урока)')
                        self.assertNotIn('Сабақ', text)
                    else:
                        self.assertRegex(text, 'Сабақ(?:тың)? тақырыбы')
                        for label in ('Тема занятия', 'Тема урока', 'План учебного занятия',
                                      'Поурочный план', 'Наименование', 'Подготовил', 'Общие сведения',
                                      'Необходимые ресурсы', 'Домашнее задание', 'Преподаватель',
                                      'Утверждаю', 'Методист колледжа', 'Ход занятия', 'Ход урока'):
                            self.assertNotIn(label, text)

    def test_export_keeps_content_and_media_without_translating_user_text(self):
        for college, config in COLLEGES.items():
            for language in ('Русский', 'Қазақша'):
                with self.subTest(college=college, language=language):
                    payload = meta_plan(language) if college == 'META' else {
                        'goal': 'Оқу мақсаты' if language == 'Қазақша' else 'Цель обучения',
                        'interdisciplinary_connections': 'Математика — есептеу',
                        'org_steps': 'Жұмыс' if language == 'Қазақша' else 'Работа',
                    }
                    literal = 'Сабақ тақырыбы: / Тема занятия: пользовательская цитата'
                    payload['resources'] = literal
                    result = build_doc('План урока', payload, template_path=config['template'],
                                       college=college, fields={'language': language, 'topic': 'Python',
                                       'date': '2026-11-23', 'subject': 'IT', 'teacher': 'Алиев А.',
                                       'course': 1, 'group': 'IT-1',
                                       'lesson_type': 'Дәріс' if language == 'Қазақша' else 'Лекция'})
                    output = Document(result)
                    text = document_text(output)
                    self.assertIn(literal, text)
                    self.assertIn('23.11.2026', text)
                    self.assertNotIn('ж/г.', text)
                    self.assertNotIn('ж./г.', text)
                    if college == 'ETEC':
                        times = []
                        for row in output.tables[1].rows[12:18]:
                            times += list(map(int, re.findall(r'(\d+)\s*мин\.', row.cells[0].text)))
                        self.assertEqual(sum(times), 90)
                    with ZipFile(config['template']) as source, ZipFile(result) as saved:
                        for name in source.namelist():
                            if name.startswith('word/media/'):
                                self.assertEqual(source.read(name), saved.read(name))
