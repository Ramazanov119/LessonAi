from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class AIConfig:
    openai_api_key: str
    openrouter_api_key: str
    openai_url: str = "https://api.openai.com/v1/chat/completions"
    openrouter_url: str = "https://openrouter.ai/api/v1/chat/completions"
    text_model: str = "gpt-4.1"
    schema_model: str = "deepseek/deepseek-chat-v3"
    timeout_seconds: float = 60.0


@dataclass(frozen=True)
class LessonRequest:
    subject: str
    topic: str
    language: str
    specialty: str
    pck: str
    lesson_type: str


@dataclass(frozen=True)
class ControlRequest:
    subject: str
    topic: str
    language: str
    specialty: str
    difficulty: str
    count: int


@dataclass(frozen=True)
class TeacherProfile:
    full_name: str
    college: str


@dataclass(frozen=True)
class LessonMetadata:
    full_name: str
    college: str
    subject: str
    topic: str
    group_name: str
    course: int
    duration: str
    lesson_date: date
    language: str
    lesson_type: str
    speciality: str
    chair: str


@dataclass(frozen=True)
class GenerationResult:
    content: str
    schema: Optional[str] = None
    visual: Optional[str] = None


@dataclass(frozen=True)
class PresentationSlide:
    title: str
    content: str
