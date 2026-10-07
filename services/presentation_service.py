import json
from dataclasses import asdict, dataclass

from services.ai import create_presentation_deck
from services.presentation_generator import render_nb_deck
from services.presenton_service import PresentonClient, PresentonServiceError


class PresentationServiceError(RuntimeError):
    """Raised when the configured presentation engine cannot create a deck."""


@dataclass(frozen=True)
class PresentationRequest:
    subject: str
    topic: str
    specialty: str
    language: str
    lesson_type: str
    lesson_duration: str
    teacher: str
    college: str
    group: str
    lesson_plan: str = ""
    lecture: str = ""
    practice: str = ""
    lesson_date: str = ""

    def source_content(self):
        sections = [
            ("Предмет", self.subject),
            ("Тема", self.topic),
            ("Специальность", self.specialty),
            ("Язык", self.language),
            ("Тип занятия", self.lesson_type),
            ("Продолжительность", self.lesson_duration),
            ("Преподаватель", self.teacher),
            ("Колледж", self.college),
            ("Группа", self.group),
            ("Дата", self.lesson_date),
            ("Поурочный план", self.lesson_plan),
            ("Лекция", self.lecture),
            ("Практическая работа", self.practice),
        ]
        return "\n\n".join(f"## {name}\n{value}" for name, value in sections if value)


@dataclass(frozen=True)
class PresentationArtifact:
    content: object
    stored_content: dict


class PresentationService:
    def __init__(self, engine, ai_config, presenton_client=None):
        self.engine = str(engine or "native").strip().lower()
        self.ai_config = ai_config
        self.presenton_client = presenton_client

    def generate(self, request):
        if self.engine == "native":
            deck = create_presentation_deck(
                {
                    "subject": request.subject,
                    "topic": request.topic,
                    "language": request.language,
                    "teacher": request.teacher,
                    "college": request.college,
                    "group": request.group,
                    "date": request.lesson_date,
                },
                request.source_content(),
                self.ai_config,
            )
            return PresentationArtifact(render_nb_deck(deck), asdict(deck))

        if self.engine == "presenton":
            if self.presenton_client is None:
                raise PresentationServiceError("Presenton client не настроен.")
            try:
                result = self.presenton_client.generate(
                    request.source_content(), request.language, n_slides=9
                )
            except PresentonServiceError as error:
                raise PresentationServiceError(str(error)) from error
            return PresentationArtifact(
                result.content,
                {
                    "engine": "presenton",
                    "presentation_id": result.presentation_id,
                    "path": result.path,
                },
            )

        raise PresentationServiceError(
            f"Неизвестный presentation engine: {self.engine}."
        )

    def download_saved(self, stored_content):
        if isinstance(stored_content, str):
            try:
                stored_content = json.loads(stored_content)
            except json.JSONDecodeError as error:
                raise PresentationServiceError("Некорректные данные презентации.") from error
        if stored_content.get("engine") != "presenton":
            return None
        if self.presenton_client is None:
            raise PresentationServiceError("Presenton client не настроен.")
        try:
            return self.presenton_client.download(stored_content.get("path", ""))
        except PresentonServiceError as error:
            raise PresentationServiceError(str(error)) from error
