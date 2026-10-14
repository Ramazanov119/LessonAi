"""Create Q samples without provider or database access."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_q_docx import q_fixture
from config.colleges import get_college_config
from services.docx_generator import build_doc


def main():
    root = Path(__file__).resolve().parents[1] / 'docs/qa/q'
    root.mkdir(parents=True, exist_ok=True)
    for language, code in (('Русский', 'ru'), ('Қазақша', 'kk')):
        plan = q_fixture(language)
        kk = code == 'kk'
        plan.update(learning_objective=plan['goal'], values='Еңбекқорлық, жауапкершілік' if kk else 'Трудолюбие, ответственность',
                    assessment_criteria='Қайталанатын есептеулерге дұрыс цикл таңдайды' if kk else 'Выбирает цикл для повторяющихся вычислений',
                    resources='Python ортасы, компьютер, тапсырма парағы' if kk else 'Среда Python, компьютер, лист заданий')
        activities = (
            ('Оқытушы білім алушылардың дайындығын тексереді.', 'Алдыңғы алгоритмдер бойынша сұрақтарға жауап береді.',
             'Қайталанатын есептеулердің мақсатын анықтайды.', 'Оқытушы for және while циклдерінің шарттарын түсіндіреді.',
             'Білім алушылар сандардың қосындысын есептейтін Python бағдарламасын жазады.', 'Кодты бірнеше енгізу мәнімен тексереді.',
             'Цикл таңдауын негіздейді.', 'Алгоритмдегі қиындықтарды талдайды.', 'Үйде циклдерді пайдаланып жаттығулар орындайды.') if kk else
            ('Преподаватель проверяет готовность студентов.', 'Студенты отвечают на вопросы по изученным алгоритмам.',
             'Определяют цель повторяющихся вычислений.', 'Преподаватель объясняет условия циклов for и while.',
             'Студенты пишут программу Python для вычисления суммы чисел.', 'Проверяют код на нескольких входных значениях.',
             'Обосновывают выбор цикла.', 'Анализируют трудности в алгоритме.', 'Дома решают упражнения с циклами.'))
        for key, content in zip(('org_steps', 'actualization', 'goal_setting', 'theory', 'practice', 'control', 'summary', 'reflection', 'homework'), activities):
            plan[key] = content
        for key in ('presentation_resource', 'actualization_resource', 'goal_setting_resource', 'presentation_demo', 'practice_result',
                    'control_resource', 'summary_resource', 'reflection_resource', 'homework_resource'):
            plan[key] = plan['resources']
        fields = dict(topic=plan['topic'], subject=plan['subject'], teacher='Тест оқытушысы' if kk else 'Тестовый преподаватель',
                      date='2026-10-13', course=1, group='IT-1', lesson_type='Жаңа сабақ' if kk else 'Новый урок', language=language)
        file = build_doc('План урока', plan, template_path=get_college_config('Q')['template'], fields=fields)
        (root / f'lesson_q_{code}.docx').write_bytes(file.getvalue())
        (root / f'lesson_q_{code}.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
