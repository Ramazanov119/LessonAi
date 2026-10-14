import json
import re

import requests

from models.generation import AIConfig, NBDeck


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


PRESENTATION_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subject": {"type": "string"},
        "teacher": {"type": "string"},
        "college": {"type": "string"},
        "group": {"type": "string"},
        "date": {"type": "string"},
        "slides": {
            "type": "array",
            "minItems": 7,
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["title", "overview", "concept", "definitions", "process", "compare", "stats", "cases"]},
                    "title": {"type": "string"},
                    "subtitle": {"type": "string"},
                    "items": {"type": "array", "items": {"type": "string"}},
                    "sections": {"type": "array", "items": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2}},
                    "terms": {"type": "array", "items": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2}},
                    "steps": {"type": "array", "items": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2}},
                    "timeline": {"type": "array", "items": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2}},
                    "comparisons": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "items": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["label", "items"],
                            "additionalProperties": False,
                        },
                    },
                    "statistics": {"type": "array", "items": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2}},
                    "highlight": {"type": "string"},
                    "code": {"type": "string"},
                },
                "required": ["kind", "title", "subtitle", "items", "sections", "terms", "steps", "timeline", "comparisons", "statistics", "highlight", "code"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "subject", "teacher", "college", "group", "date", "slides"],
    "additionalProperties": False,
}


def _parse_json_content(content, provider):
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise AIServiceError(f"{provider}: модель вернула некорректную структуру презентации.") from error


def _presentation_prompt(metadata, source_content):
    return f"""Создай содержательную учебную презентацию для колледжа.
Язык презентации: {metadata['language']}.
Предмет: {metadata['subject']}
Тема: {metadata['topic']}
Преподаватель: {metadata['teacher']}
Колледж: {metadata['college']}
Группа: {metadata['group']}
Дата: {metadata['date']}

Используй 7–12 слайдов. Первый слайд имеет kind=title. Затем выбери подходящие
композиции; не добавляй вымышленные факты и числовую статистику. Текст должен
быть кратким, пригодным для показа на экране, без markdown. Верни только JSON.

Исходный учебный материал:
{source_content[:24000]}
"""


def create_presentation_deck(metadata, source_content, config):
    """Generate a validated deck model through a swappable AI provider."""
    prompt = _presentation_prompt(metadata, source_content)
    provider = config.presentation_provider.strip().lower()

    if provider == "gemini":
        if not config.gemini_api_key:
            raise AIServiceError("Gemini: добавьте GEMINI_API_KEY в Streamlit secrets.")
        model = config.presentation_model.removeprefix("google/")
        data = _request_json(
            f"{config.gemini_url}/models/{model}:generateContent?key={config.gemini_api_key}",
            {"Content-Type": "application/json"},
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.35,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": PRESENTATION_SCHEMA,
                },
            },
            "Gemini",
            config.timeout_seconds,
        )
        try:
            content = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as error:
            raise AIServiceError("Gemini: в ответе отсутствует презентация.") from error
    elif provider == "openrouter":
        payload = {
            "model": config.presentation_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.35,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "lesson_presentation", "strict": True, "schema": PRESENTATION_SCHEMA},
            },
        }
        data = _request_json(
            config.openrouter_url,
            {"Authorization": f"Bearer {config.openrouter_api_key}", "Content-Type": "application/json"},
            payload,
            "OpenRouter",
            config.timeout_seconds,
        )
        content = _content_from_response(data, "OpenRouter")
    else:
        raise AIServiceError(f"Неизвестный провайдер презентаций: {provider}")

    generated = _parse_json_content(content, provider)
    generated.update(
        title=metadata["topic"],
        subject=metadata["subject"],
        teacher=metadata["teacher"],
        college=metadata["college"],
        group=metadata["group"],
        date=metadata["date"],
    )
    deck = NBDeck.from_dict(generated)
    if len(deck.slides) < 2 or deck.slides[0].kind != "title":
        raise AIServiceError("Модель вернула неполную презентацию.")
    return deck


def create_lesson(
    subject,
    topic,
    language,
    specialty,
    pck,
    lesson_type,
    lesson_duration,
    config,
    *,
    college=None,
    lesson_date=None,
):
    if str(college or "").upper() == "META":
        from config.colleges import get_college_config
        lesson_duration = get_college_config("META")["lesson_duration"]
    system = """
Ты опытный методист колледжа Казахстана, специализирующийся на разработке
учебных занятий для системы ТиПО.

Используй официальный методический стиль ТиПО и таксономию Блума.

Верни только корректный JSON без markdown и пояснений.

JSON должен содержать непустые строковые поля:

goal, tasks, results, resources,
org_steps, presentation_resource,
actualization, actualization_resource,
goal_setting, goal_setting_resource,
theory, presentation_demo,
practice, practice_resource,
control, control_resource,
summary, summary_resource,
reflection, reflection_resource,
homework, homework_resource,
peer_assessment, assessment_sheet,
assessment, assessment_activity,
evaluation_criteria,
explanatory_illustrative_method,
practical_task,
interdisciplinary_connections,
learning_objective,
assessment_criteria,
values,
learning_goal,
developmental_goal,
educational_goal.

Каждый раздел должен быть содержательно заполнен и соответствовать теме,
типу урока, специальности и практической деятельности студентов.

### ЦЕЛЬ ЗАНЯТИЯ
### ЦЕЛИ УРОКА ДЛЯ АТКК

Поле learning_goal — обучающая цель.
Опиши, какие конкретные знания, умения или навыки обучающийся
должен приобрести или освоить на занятии.

Поле developmental_goal — развивающая цель.
Опиши, какие интеллектуальные, профессиональные, аналитические,
логические, коммуникативные или практические способности
развиваются у обучающегося на занятии.

Поле educational_goal — воспитывающая цель.
Опиши, какие профессиональные и личностные качества формируются:
ответственность, дисциплинированность, аккуратность, трудолюбие,
самостоятельность, культура труда, командная работа и т.д.

Все три цели должны соответствовать конкретной теме,
специальности и типу занятия.
Не повторяй одну и ту же формулировку в разных целях.

### ОБУЧАЮЩАЯ ЦЕЛЬ

Поле learning_objective должно содержать краткую конкретную
обучающую цель занятия.

Она должна быть согласована с темой, специальностью,
типом урока, полем goal и практическим заданием.

Используй конкретный деятельностный глагол таксономии Блума.
Формулировка должна описывать, что именно студент должен
научиться выполнять на занятии.

Поле goal должно:

- обязательно начинаться со слова «Научить»;
- содержать конкретный и измеримый результат обучения;
- использовать деятельностные глаголы, соответствующие таксономии Блума;
- не повторять название темы без конкретизации;
- соответствовать содержанию практической части занятия.

Пример:
«Научить студентов применять линейные алгоритмы для решения
практических задач средствами языка C#».

### ҚҰНДЫЛЫҚТАР

Поле values должно содержать воспитательные ценности,
соответствующие теме и содержанию занятия.

Выбирай ценности не случайно, а исходя из содержания урока,
деятельности студентов и профессионального контекста.

Используй такие ценности, как:
- білімге ұмтылу;
- адал азамат;
- мейірім, рақым, адамға сүйіспеншілік, ар-ождан;
- еңбекқорлық, табандылық, ерік-жігер, әрекетке көшу;
и другие соответствующие ценности.

Формулировка должна быть краткой и конкретной.
Если для занятия подходят несколько ценностей, укажи их через запятую.

### ЗАДАЧИ ЗАНЯТИЯ

Поле tasks должно содержать конкретные учебные задачи,
сформулированные с использованием деятельностных глаголов
таксономии Блума.

Используй в зависимости от содержания темы такие глаголы, как:

- определить;
- описать;
- объяснить;
- классифицировать;
- сравнить;
- применить;
- решить;
- проанализировать;
- оценить;
- обосновать;
- разработать;
- создать.

Не используй в качестве основных формулировок неконкретные глаголы:
«знать», «понимать», «изучить», «ознакомиться».

Не требуется использовать все уровни таксономии Блума.
Выбирай только те уровни и глаголы, которые соответствуют теме,
типу урока и уровню подготовки студентов.

Задачи должны быть согласованы с целью, ожидаемыми результатами,
практическим заданием и критериями оценивания.

### РЕЗУЛЬТАТЫ ОБУЧЕНИЯ

Поле results должно описывать конкретные действия,
которые студент сможет выполнить после занятия.

Используй измеримые глаголы таксономии Блума.
Результаты должны быть проверяемыми посредством практического задания
или оценивания.

### НЕОБХОДИМЫЕ РЕСУРСЫ

Поле resources должно содержать необходимые для занятия:

- оборудование;
- программное обеспечение;
- учебные материалы;
- учебники и книги;
- научные и методические статьи;
- официальную документацию;
- электронные образовательные ресурсы;
- обучающие видеоматериалы.

Внешние источники должны быть релевантными теме.
Не придумывай URL, названия книг, авторов или библиографические данные.
Если достоверность URL невозможно проверить, укажи название ресурса
без ссылки.

Поле assessment_activity должно содержать краткое описание
действия преподавателя/студентов на этапе проверки и оценивания
практической работы.

### УЧЕБНЫЕ РЕСУРСЫ ПО ЭТАПАМ УРОКА

Для каждого этапа урока отдельно указывай учебные ресурсы и материалы,
которые непосредственно используются на данном этапе.

Поле presentation_resource:
ресурсы для организационного этапа и мотивации.
Например: презентация, изображение, короткое видео,
демонстрационный материал.

Поле actualization_resource:
ресурсы для актуализации ранее изученных знаний и проверки
домашнего задания.
Например: вопросы, карточки, тест, задания,
предыдущие учебные материалы.

Поле goal_setting_resource:
ресурсы для этапа целеполагания.
Например: проблемный вопрос, кейс, изображение,
ситуационная задача, тема на экране или презентация.

Поле presentation_demo:
ресурсы и демонстрационные материалы для объяснения нового материала.
Например: презентация, схема, таблица, пример программы,
фрагмент кода, документация или демонстрация.

Поле practice_resource:
ресурсы для выполнения практического задания.
Например: компьютер, программное обеспечение, оборудование,
исходные данные, файлы, инструкция, карточки заданий.

Поле control_resource:
ресурсы для контроля и самоконтроля.
Например: тест, контрольные вопросы, чек-лист,
критерии оценивания или контрольное задание.

Поле assessment_criteria должно содержать краткие критерии
оценивания, непосредственно предназначенные для вставки
в шаблон документа.

Критерии должны быть конкретными, измеримыми и соответствовать
результатам обучения и практическому заданию.

Не используй общие формулировки вроде «понимает тему»,
«знает материал» или «активно участвует».

Поле summary_resource:
ресурсы для обобщения и систематизации знаний.
Например: итоговая схема, таблица, вопросы,
ментальная карта или опорный материал.

Поле reflection_resource:
ресурсы для проведения рефлексии.
Например: вопросы для рефлексии, карточка,
анкета или цифровой инструмент.

Поле homework_resource:
ресурсы, необходимые для выполнения домашнего задания.
Например: учебник, официальная документация,
статья, методические материалы или электронный образовательный ресурс.

Если отдельный ресурс на этапе не требуется,
укажи «Не требуется».

Не дублируй поле resources во всех этапах.
Поле resources содержит общий перечень необходимых ресурсов всего занятия,
а поля *_resource содержат ресурсы конкретного этапа.

Формулировка должна быть на языке занятия и соответствовать
языку, указанному в поле language.

Не используй фиксированный русский текст независимо от языка.

### ЯЗЫК ГЕНЕРАЦИИ

Весь генерируемый материал должен быть полностью написан
на языке, указанном в поле «Язык».

Это правило распространяется на все поля JSON:
goal, tasks, results, resources, org_steps,
presentation_resource, actualization, actualization_resource,
goal_setting, goal_setting_resource, theory, presentation_demo,
practice, practice_resource, control, control_resource,
summary, summary_resource, reflection, reflection_resource,
homework, homework_resource, peer_assessment,
assessment_sheet, assessment, assessment_activity,
evaluation_criteria и остальные текстовые поля.

Если выбран русский язык — весь текст должен быть на русском.
Если выбран казахский язык — весь текст должен быть на казахском.
Если выбран английский язык — весь текст должен быть на английском.

Не смешивай языки внутри одного поля, за исключением:
- названий программного обеспечения;
- названий языков программирования;
- официальных названий документов;
- общепринятых технических терминов и аббревиатур.

### КРИТЕРИИ ОЦЕНИВАНИЯ

Поле evaluation_criteria должно содержать конкретные,
измеримые и понятные преподавателю критерии оценивания.

Критерии должны непосредственно соответствовать:
- результатам обучения;
- практическому заданию;
- содержанию урока.

Избегай общих формулировок вроде «понимает тему» или «активно участвует».

Поля explanatory_illustrative_method, practical_task и
interdisciplinary_connections должны быть заполнены коротко,
но содержательно, чтобы их можно было непосредственно вставить
в шаблон урока без дополнительной доработки.

"""    
    prompt = f"""

Создай профессиональный поурочный план занятия для колледжа Казахстана.

Используй таксономию Блума, конкретные измеримые результаты
и критерии оценивания.

Структура занятия должна быть логически связанной:

1. Организационный этап
2. Актуализация знаний и проверка домашнего задания
3. Целеполагание
4. Формирование новых знаний и способов деятельности
5. Закрепление и применение новых знаний
6. Контроль и самоконтроль
7. Обобщение и систематизация знаний
8. Рефлексия
9. Домашнее задание

Для каждого этапа обязательно сформируй:
- деятельность преподавателя и студентов;
- соответствующий учебный ресурс или материал.

Ресурс должен соответствовать именно деятельности данного этапа,
а не быть простым повторением общего списка ресурсов.

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

Продолжительность занятия:
{lesson_duration} минут.

Распредели этапы занятия реалистично по времени.
Значения time1–time7 должны соответствовать структуре занятия.
Сумма всех временных интервалов занятия должна быть РОВНО равна
{lesson_duration} минутам.

Не превышай и не уменьшай общую продолжительность занятия.
Проверь арифметическую сумму time1–time7 перед формированием JSON.

"""
    from services.lesson_validation import normalize_meta_lesson, lesson_date_value, BLOOM_LEVELS, language_code
    from config.colleges import get_college_config
    if str(college or "").upper() == "META":
        # Extend the existing request; no additional provider call.
        lesson_duration = get_college_config("META")["lesson_duration"]
        levels = ", ".join(BLOOM_LEVELS[language_code(language)])
        system = system.replace(
            '- обязательно начинаться со слова «Научить»;',
            '- начинаться с глагола обучения на выбранном языке: «Научить», «Үйрету» или «Teach»;',
        )
        prompt += f"""
Дополнительная структура для META College, продолжительность {lesson_duration} минут.
Кроме существующих строковых полей добавь:
lesson_duration: {lesson_duration},
lesson_stages: массив объектов с field_key, name, duration_minutes (целое > 0), content, tasks.
tasks — массив реальных заданий этого этапа: {{"id": "task_1", "name": "задание", "instruction": "действия студентов"}}.
id уникален во всём уроке; содержание и инструкции согласованы. Для этапа без заданий tasks = [].
field_key по порядку: org_steps, actualization, theory, practice, homework, assessment, reflection.
name и content — на языке {language}. content совпадает с соответствующим строковым полем.
Распредели время по типу занятия {lesson_type}; для практики/лабораторной выдели больше времени
на самостоятельную работу, для лекции — на объяснение. Сумма ровно {lesson_duration}.
Не указывай время внутри name/content; минуты хранятся только в duration_minutes.
assessment_items: массив объектов с task_id, task_name, stage_key, bloom_level,
assessment_criterion, descriptors, points (необязательный положительный числовой относительный вес).
stage_key — field_key этапа, в котором студенты выполняют задание.
task_id точно ссылается на id существующего задания в tasks этапа; каждое задание оценивается один раз.
task_name — название задания для таблицы, его не нужно дословно копировать в описание content.
Не добавляй в оценивание задания, которых нет в tasks соответствующего этапа.
Уровни Блума на выбранном языке: {levels}.
Дескрипторы — массив объектов {{"task_id": "task_1", "text": "Аргументирует выводы с примерами", "action": "Аргументирует выводы", "result": "Примеры в обосновании", "points": 5}}; все тексты переведи на выбранный язык.
Не вписывай баллы внутрь text. points дескрипторов — положительные относительные веса внутри задания; Python рассчитывает итоговые баллы.
Предлагай веса согласно значимости заданий; точную сумму 100 обеспечивает Python. Не копируй образец универсальных заданий.
Подбирай конкретные задания, критерии и дескрипторы по теме, целям, результатам,
теоретическому материалу, практике и деятельности обучающихся в данном плане.
Критерий должен измерять выполнение именно этого задания, дескрипторы раскрывают критерий.
Не требуй повторения слов темы или задания в критериях и дескрипторах.
Критерий и каждый дескриптор относятся к task_id своей строки оценивания.
Дескрипторы — объекты с task_id, text, action (наблюдаемое действие),
result (при необходимости измеримый результат) и points.
Допустимы перефразировки, например «Аргументирует выводы с примерами».
Не используй субъективные качества и непроверяемое «понимает» вместо наблюдаемого действия.
Текст, action и result должны быть согласованы; result обязателен, если requires_result=true.
Математическое распределение баллов и времени выполняет приложение после ответа; не добавляй meta_schema_version или технические поля приложения.
Все значения, включая заголовки, уровни Блума, дескрипторы, названия и описание методов
(explanatory_illustrative_method) и практических заданий (practical_task) — на языке {language}.
"""
    if str(college or "").upper() == "Q":
        prompt += f"""
Для Q College заполни строковое поле interdisciplinary_connections.
Определи обычно 1–3 действительно связанных предмета по дисциплине {subject}, теме {topic},
специальности {specialty} и сформулированным целям занятия.
Формат: «Дисциплина — конкретные используемые знания или навыки»; связи разделяй точкой с запятой.
Не ограничивайся перечнем предметов, не добавляй искусственные связи и длинные объяснения.
Не утверждай, что предмет входит в учебный план специальности: таких данных нет.
Поле полностью на языке {language}. Это дополнительный элемент шаблона Q,
не утверждай его обязательность по приказу № 130.
"""
    system += "\nДату не придумывай: поля date/data не генерируй, дата подставляется приложением."
    generated = openai_generate(prompt, system, config)
    if str(college or "").upper() == "META":
        import uuid
        from services.meta_diagnostics import record_meta_response
        attempt_id = uuid.uuid4().hex
        record_meta_response(generated, 'ai_raw', attempt_id)
        try:
            from services.lesson_validation import parse_lesson
            raw = parse_lesson(generated)
            raw.pop('meta_schema_version', None)
            raw.pop('meta_attempt_id', None)
            payload = normalize_meta_lesson(raw, language=language, lesson_type=lesson_type,
                                            lesson_date=lesson_date)
        except ValueError as error:
            from services.meta_diagnostics import record_meta_failure
            record_meta_failure(generated, error, "normalization")
            record_meta_response(generated, 'normalization_failed', attempt_id, error)
            raise AIServiceError(str(error)) from error
        payload['meta_attempt_id'] = attempt_id
        record_meta_response(payload, 'normalized', attempt_id)
        return json.dumps(payload, ensure_ascii=False)
    # Keep the existing return type while removing AI dates from the saved plan.
    from services.lesson_validation import parse_lesson
    payload = parse_lesson(generated)
    if str(college or "").upper() == "Q":
        from services.q_docx import q_connections
        try:
            payload['interdisciplinary_connections'] = q_connections(payload)
        except ValueError as error:
            raise AIServiceError(str(error)) from error
    selected = lesson_date_value(lesson_date).isoformat()
    payload.update(date=selected, data=selected, lesson_date=selected)
    return json.dumps(payload, ensure_ascii=False)


def create_lecture(subject, topic, language, specialty, pck, lesson_type, config):
    system = """
Ты методист колледжа Казахстана. Пиши академичный и профессиональный материал
для преподавателя, по таксономии Блума, с конкретными измеримыми результатами
и критериями оценивания.

Верни строго JSON-объект, без markdown, без вводных слов, без текста вне JSON.

Нужные поля:
{
  "title": "строка",
  "relevance": "строка",
  "learning_goals": ["строка", "строка"],
  "key_terms": [{"term": "строка", "definition": "строка"}],
  "values": ["строка"],
  "main_material": [
    {
      "title": "строка",
      "content": "строка",
      "examples": ["строка"]
    }
  ],
  "practice_examples": ["строка", "строка"],
  "case_study": {
    "scenario": "строка",
    "analysis": "строка",
    "solution": "строка"
  },
  "common_errors": [
    {
      "error": "строка",
      "why": "строка",
      "fix": "строка"
    }
  ],
  "summary": ["строка", "строка"],
  "review_questions": ["строка", "строка"],
  "preparation_for_practice": "строка",
  "assessment_activity": "строка"
}

Правила:
- Делай материал содержательным, научным и применимым в реальной профессии.
- Не пиши общие слова, без конкретики и повторов.
- Для технических тем добавляй корректные термины, алгоритмы, примеры,
  таблицы в текстовом виде при необходимости.
- Для гуманитарных или экономических тем используй реальные профессиональные ситуации.
- Длина — 4–8 страниц A4 эквивалентного текста, не больше и не меньше по смыслу.
- Не включай текст вне JSON.
- Не используй сокращения без расшифровки.
- Весь материал должен быть написан на языке, указанном в поле «Язык».
- Не смешивай языки внутри одного поля, кроме названий программного обеспечения,
  языков программирования, официальных названий документов,
  общепринятых технических терминов и аббревиатур.
"""

    prompt = f"""
Создай учебно-методическую лекцию для колледжа.

Предмет: {subject}
Тема: {topic}
Язык: {language}
Специальность: {specialty}
Председатель ПЦК: {pck}
Тип урока: {lesson_type}

Сделай лекцию структурированной по разделам но название разделов должно быть на языке занятия:

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

Весь текст лекции должен быть на выбранном языке.
"""

    return openai_generate(prompt, system, config)


def rework_lecture(lecture_text, style, config, *, language="Русский"):
    system = f"""
Ты методист колледжа. Перерабатываешь существующую лекцию, сохраняя её тему и смысл, но усиливая качество.

Верни только JSON-объект в той же структуре, что и исходная лекция.
Нельзя писать текст вне JSON.

Настройка переработки: {style}
Язык лекции: {language}. Весь текст, включая названия разделов и примеры, должен быть на этом языке.

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
    """Create a hands-on, practice aligned to its lesson materials."""
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
структуру JSON и длительность {lesson_duration}. Верни только корректный JSON в той же
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
