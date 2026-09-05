import requests

from models.generation import AIConfig


class AIServiceError(RuntimeError):
    """Raised when an AI provider cannot return a usable response."""


def _request_json(url, headers, payload, provider, timeout_seconds):
    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except requests.Timeout as error:
        raise AIServiceError(
            f"{provider}: сервис не ответил вовремя. Повторите попытку."
        ) from error
    except requests.HTTPError as error:
        status_code = error.response.status_code if error.response else "неизвестен"
        raise AIServiceError(
            f"{provider}: API вернул HTTP-ошибку {status_code}."
        ) from error
    except requests.RequestException as error:
        raise AIServiceError(
            f"{provider}: не удалось подключиться к API. Проверьте сеть и настройки."
        ) from error

    try:
        return response.json()
    except ValueError as error:
        raise AIServiceError(
            f"{provider}: API вернул некорректный ответ."
        ) from error


def _content_from_response(data, provider):
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        if isinstance(data, dict) and data.get("error"):
            raise AIServiceError(f"{provider}: {data['error']}") from error
        raise AIServiceError(
            f"{provider}: в ответе отсутствует текст генерации."
        ) from error

    if not isinstance(content, str):
        raise AIServiceError(f"{provider}: текст генерации имеет неверный формат.")
    return content


def openai_generate(prompt, system, config):
    headers = {
        "Authorization": f"Bearer {config.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.text_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.5,
    }
    data = _request_json(
        config.openai_url,
        headers,
        payload,
        "OpenAI",
        config.timeout_seconds,
    )
    return _content_from_response(data, "OpenAI")


def openrouter_generate(prompt, config):
    headers = {
        "Authorization": f"Bearer {config.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.schema_model,
        "messages": [{"role": "user", "content": prompt}],
    }
    data = _request_json(
        config.openrouter_url,
        headers,
        payload,
        "OpenRouter",
        config.timeout_seconds,
    )
    return _content_from_response(data, "OpenRouter")


def create_lesson(subject, topic, language, specialty, pck, lesson_type, config):
    system = """

Ты опытный методист колледжа Казахстана.

Используй официальный стиль ТиПО.

Верни только корректный JSON без markdown и пояснений. JSON должен содержать
непустые строковые поля:
goal, tasks, results, resources, org_steps, presentation_resource,
theory, presentation_demo, practice, practice_result, peer_assessment,
reflection, assessment_sheet, homework, actualization, actualization_resource,
assessment, evaluation_criteria, explanatory_illustrative_method,
practical_task, interdisciplinary_connections, date, time1, time2, time3,
time4, time5, time6, time7.

Заполняй каждый раздел содержательно и не оставляй поля пустыми.

Поле evaluation_criteria должно содержать конкретные критерии оценивания
результатов работы студентов по теме урока. Критерии должны быть измеримыми,
понятными преподавателю и соответствовать содержанию практической части урока.

Поля explanatory_illustrative_method, practical_task и
interdisciplinary_connections должны быть заполнены коротко, но содержательно,
чтобы их можно было вставить в шаблон урока без дополнительной доработки.

"""
    prompt = f"""

Создай профессиональный план урока.

Предмет:

{subject}

Тема:

{topic}

Язык:

{language}

Специальность:

{specialty}

Председатель ПЦК:

{pck}

Тип урока:

{lesson_type}

"""
    return openai_generate(prompt, system, config)


def create_lecture(subject, topic, language, specialty, pck, lesson_type, config):
    system = """
Ты методист колледжа Казахстана. Пиши академичный и профессиональный материал для преподавателя.

Верни строго JSON-объект, без markdown, без вводных слов, без текста вне JSON.
Нужные поля:
{
  "title": "строка",
  "relevance": "строка",
  "learning_goals": ["строка", "строка"],
  "key_terms": [{"term": "строка", "definition": "строка"}],
  "main_material": [{"title": "строка", "content": "строка", "examples": ["строка"]}],
  "practice_examples": ["строка", "строка"],
  "case_study": {"scenario": "строка", "analysis": "строка", "solution": "строка"},
  "common_errors": [{"error": "строка", "why": "строка", "fix": "строка"}],
  "summary": ["строка", "строка"],
  "review_questions": ["строка", "строка"],
  "preparation_for_practice": "строка"
}

Правила:
- Делай материал содержательным, научным и применимым в реальной профессии.
- Не пиши общие слова, без конкретики и повторов.
- Для технических тем добавляй корректные термины, алгоритмы, примеры, таблицы в текстовом виде при необходимости.
- Для гуманитарных или экономических тем используй реальные профессиональные ситуации.
- Длина — 4–8 страниц A4 эквивалентного текста, не больше и не меньше по смыслу.
- Не включай текст вне JSON.
"""
    prompt = f"""
Создай учебно-методическую лекцию для колледжа.

Предмет: {subject}
Тема: {topic}
Язык: {language}
Специальность: {specialty}
Председатель ПЦК: {pck}
Тип урока: {lesson_type}

Сделай лекцию структурированной по разделам:
1. Тема
2. Актуальность
3. Цели обучения
4. Ключевые понятия
5. Основной теоретический материал
6. Практические примеры
7. Разбор типичной ситуации
8. Типичные ошибки
9. Краткое резюме
10. Вопросы для закрепления
11. Подготовка к практическому занятию
"""
    return openai_generate(prompt, system, config)


def rework_lecture(lecture_text, style, config):
    system = f"""
Ты методист колледжа. Перерабатываешь существующую лекцию, сохраняя её тему и смысл, но усиливая качество.

Верни только JSON-объект в той же структуре, что и исходная лекция.
Нельзя писать текст вне JSON.

Настройка переработки: {style}

Правила:
- сохраняй тему и учебный контекст;
- усиливай содержательность, научность и профессиональную применимость;
- добавляй практические примеры, кейсы или таблицы там, где это уместно;
- убирай повторы и общие фразы;
- не меняй объем резко, но делай материал более полезным для реального занятия.
"""
    prompt = f"""
Ниже — текущая лекция. Переработай её в соответствии с выбранным вариантом.

{lecture_text}

Вариант переработки: {style}
"""
    return openai_generate(prompt, system, config)


def create_control(subject, topic, language, specialty, difficulty, count, config):
    system = """

Создай контрольную работу.

Автоматически решай:

нужна ли:

- схема
- диаграмма
- блок схема
- рисунок

Если нужно:

добавь пометки:

[SCHEMA]

[DRAW]

"""
    prompt = f"""

Предмет:

{subject}

Тема:

{topic}

Язык:

{language}

Специальность:

{specialty}

Сложность:

{difficulty}

Количество заданий:

{count}

"""
    return openai_generate(prompt, system, config)


def create_practice(
    subject,
    topic,
    language,
    specialty,
    lesson_type,
    *,
    lesson_plan=None,
    lecture=None,
    config,
):
    """Create a hands-on, 70-minute practice aligned to its lesson materials."""
    system = """
Ты методист колледжа Казахстана. Создай практическое занятие, в котором
студент выполняет реальную профессиональную работу, а не пересказывает лекцию.

Верни только корректный JSON без markdown и текста вне JSON. Обязательная структура:
{
  "title": "строка",
  "objective": "строка",
  "learning_outcomes": ["строка"],
  "required_tools": ["строка"],
  "safety_notes": ["строка"],
  "brief_theory": "строка",
  "professional_context": "строка",
  "main_task": "строка",
  "task_steps": ["строка"],
  "individual_variants": ["строка"],
  "expected_result": "строка",
  "evaluation_criteria": [{"criterion": "строка", "weight": "число%"}],
  "control_questions": ["строка"],
  "reflection": ["строка"],
  "conclusion": "строка",
  "time_allocation": [{"stage": "строка", "minutes": число}]
}

Правила качества:
- Практика должна соответствовать теме и специальности, быть выполнимой за 70 минут.
- Дай 3–5 измеримых результатов, 5–10 конкретных шагов и 5–7 контрольных вопросов.
- Теория занимает не более 10–15% материала; основная часть — практическая работа.
- Профессиональная ситуация, основное задание и ожидаемый результат должны быть конкретными.
- Если техника безопасности не требуется, верни пустой массив safety_notes.
- Время в time_allocation обязано суммарно равняться 70 минутам.
"""
    prompt = f"""
Создай учебно-методическое практическое занятие.

Предмет: {subject}
Тема: {topic}
Язык: {language}
Специальность: {specialty}
Тип урока: {lesson_type}

Используй следующий контекст уже созданных материалов, если он передан. Не меняй тему.

Поурочный план:
{lesson_plan or "Не создан"}

Лекция:
{lecture or "Не создана"}
"""
    return openai_generate(prompt, system, config)


def rework_practice(practice_text, style, *, lesson_plan=None, lecture=None, config):
    """Improve an existing practice without changing its lesson or duration."""
    system = """
Ты методист колледжа. Переработай практическое занятие, сохранив его тему,
структуру JSON и длительность 70 минут. Верни только корректный JSON в той же
структуре, без markdown и текста вне JSON. Практика должна оставаться конкретной,
профессиональной и выполнимой в рамках одного занятия.
"""
    prompt = f"""
Текущее практическое занятие:
{practice_text}

Вариант переработки: {style}

Контекст поурочного плана:
{lesson_plan or "Не создан"}

Контекст лекции:
{lecture or "Не создана"}
"""
    return openai_generate(prompt, system, config)


def create_schema(topic, config):
    prompt = f"""

Создай Mermaid диаграмму.

Тема:

{topic}

Верни только Mermaid.

"""
    return openrouter_generate(prompt, config)


def create_visual(topic, config):
    prompt = f"""

Создай описание рисунка.

Тема:

{topic}

Верни:

тип рисунка

что должно быть изображено

"""
    return openrouter_generate(prompt, config)