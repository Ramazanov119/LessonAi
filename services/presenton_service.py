from dataclasses import dataclass
from io import BytesIO
from urllib.parse import urlparse

import requests


class PresentonServiceError(RuntimeError):
    """Raised when the external Presenton service cannot produce a PPTX."""


@dataclass(frozen=True)
class PresentonResult:
    presentation_id: str
    path: str
    content: BytesIO


class PresentonClient:
    GENERATE_PATH = "/api/v1/ppt/presentation/generate"

    def __init__(self, base_url, api_key="", timeout_seconds=180.0):
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.timeout_seconds = float(timeout_seconds)

    def _headers(self):
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _ensure_configured(self):
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise PresentonServiceError(
                "Presenton не настроен: укажите корректный PRESENTON_BASE_URL."
            )

    def _download_url(self, path):
        parsed = urlparse(str(path or ""))
        if not parsed.path or parsed.scheme or parsed.netloc:
            raise PresentonServiceError("Presenton вернул небезопасный путь к презентации.")
        return f"{self.base_url}/{parsed.path.lstrip('/')}"

    def _download(self, path):
        try:
            response = requests.get(
                self._download_url(path),
                headers=self._headers(),
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except (requests.Timeout, requests.ConnectionError) as error:
            raise PresentonServiceError(
                "Сервис генерации презентаций временно недоступен."
            ) from error
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code >= 500:
                raise PresentonServiceError(
                    "Сервис генерации презентаций временно недоступен."
                ) from error
            raise PresentonServiceError(
                "Не удалось скачать презентацию из Presenton."
            ) from error
        except requests.RequestException as error:
            raise PresentonServiceError(
                "Не удалось скачать презентацию из Presenton."
            ) from error

        if not response.content.startswith(b"PK"):
            raise PresentonServiceError("Presenton вернул файл в неожиданном формате.")
        return BytesIO(response.content)

    def generate(self, content, language, *, n_slides=9):
        self._ensure_configured()
        payload = {
            "content": content,
            "instructions": (
                "Используй только предоставленный учебный материал. Не изменяй тему, "
                "предмет, ФИО преподавателя, колледж или группу. Не выполняй поиск в "
                "интернете. Подготовь учебную презентацию для показа студентам."
            ),
            "tone": "educational",
            "verbosity": "standard",
            "web_search": False,
            "n_slides": max(7, min(12, int(n_slides))),
            "language": language,
            "include_table_of_contents": False,
            "include_title_slide": True,
            "export_as": "pptx",
        }
        try:
            response = requests.post(
                f"{self.base_url}{self.GENERATE_PATH}",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.Timeout, requests.ConnectionError) as error:
            raise PresentonServiceError(
                "Сервис генерации презентаций временно недоступен."
            ) from error
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code >= 500:
                raise PresentonServiceError(
                    "Сервис генерации презентаций временно недоступен."
                ) from error
            raise PresentonServiceError(
                "Presenton отклонил запрос. Проверьте URL и API key."
            ) from error
        except (requests.RequestException, ValueError) as error:
            raise PresentonServiceError(
                "Presenton не смог создать презентацию. Проверьте его настройки."
            ) from error

        presentation_id = str(data.get("presentation_id", "")).strip()
        path = str(data.get("path", "")).strip()
        if not presentation_id or not path:
            raise PresentonServiceError("Presenton вернул неполный ответ.")
        return PresentonResult(presentation_id, path, self._download(path))

    def download(self, path):
        self._ensure_configured()
        return self._download(path)
