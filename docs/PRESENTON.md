# Presenton для LessonAI

Presenton запускается отдельным сервисом. LessonAI обращается к нему по HTTP;
пакеты Presenton не устанавливаются в окружение Streamlit.

```text
Streamlit LessonAI -> HTTP -> Presenton -> PPTX
```

## Запуск на macOS через Docker

Установите Docker Desktop. Для proof-of-concept можно использовать локальную
текстовую модель Ollama и полностью отключить генерацию изображений:

```bash
mkdir -p presenton-data

docker run --name presenton \
  -p 5001:80 \
  -e AUTH_USERNAME=admin \
  -e AUTH_PASSWORD=replace-with-a-long-password \
  -e LLM=ollama \
  -e OLLAMA_MODEL=qwen3:8b \
  -e DISABLE_IMAGE_GENERATION=true \
  -e WEB_GROUNDING=false \
  -e PRESENTON_COMMUNITY_ENABLED=false \
  -e PRESENTATION_GENERATION_MODE=standard \
  -e CAN_CHANGE_KEYS=false \
  -e DISABLE_ANONYMOUS_TRACKING=true \
  -v "$(pwd)/presenton-data:/app_data" \
  ghcr.io/presenton/presenton:latest
```

Откройте `http://localhost:5001`, войдите под созданным администратором и
создайте API key в разделе Admin → API keys. Современный Presenton требует ключ
для маршрутов `/api/v1/`.

Если Presenton в выбранной версии не может связаться с Ollama, сначала запустите
Ollama на macOS и укажите его адрес согласно документации используемого образа.
Это касается только текстовой модели; платный image provider для PoC не нужен.

Повторный запуск контейнера:

```bash
docker start presenton
```

Логи и остановка:

```bash
docker logs -f presenton
docker stop presenton
```

## Настройка LessonAI

Добавьте в локальный `.streamlit/secrets.toml`:

```toml
PRESENTATION_ENGINE = "presenton"
PRESENTON_BASE_URL = "http://localhost:5001"
PRESENTON_API_KEY = "sk-presenton-..."
PRESENTON_TIMEOUT_SECONDS = 180
```

Чтобы вернуться к существующему генератору LessonAI:

```toml
PRESENTATION_ENGINE = "native"
```

`native` используется по умолчанию. Не добавляйте реальные API keys в Git.

## Что отправляется в Presenton

LessonAI передаёт предмет, тему, специальность, язык, тип и длительность урока,
ФИО преподавателя, колледж, группу, дату, поурочный план, лекцию и практическую
работу. В запросе явно отключён web search. Запрашивается девять слайдов в
допустимом диапазоне 7–12 и экспорт в PPTX.

В базе LessonAI сохраняются только `presentation_id` и относительный путь к
файлу. Поэтому каталог `/app_data` должен быть подключён как постоянный Docker
volume: он нужен для повторного скачивания презентаций.

## Проверка API

После создания Presenton API key:

```bash
curl -X POST http://localhost:5001/api/v1/ppt/presentation/generate \
  -H "Authorization: Bearer sk-presenton-REPLACE" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Тестовый учебный материал",
    "n_slides": 7,
    "language": "Русский",
    "web_search": false,
    "export_as": "pptx"
  }'
```

Ответ должен содержать `presentation_id` и относительный `path` к PPTX.
