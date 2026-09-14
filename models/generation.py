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


@dataclass(frozen=True)
class NBSlide:
    """A single slide in a NotebookLM-style visual presentation.

    ``kind`` selects the visual composition used by the renderer:
    title, overview, concept, definitions, process, compare, stats,
    cases, code, summary. Unknown kinds fall back to a simple layout.
    """

    kind: str
    title: str
    subtitle: str = ""
    items: tuple[str, ...] = ()
    sections: tuple[tuple[str, str], ...] = ()
    terms: tuple[tuple[str, str], ...] = ()
    steps: tuple[tuple[str, str], ...] = ()
    timeline: tuple[tuple[str, str], ...] = ()
    comparisons: tuple[tuple[str, tuple[str, ...]], ...] = ()
    statistics: tuple[tuple[str, str], ...] = ()
    highlight: str = ""
    code: str = ""


@dataclass(frozen=True)
class NBDeck:
    """Top-level NotebookLM-style presentation structure."""

    title: str
    subject: str
    teacher: str
    college: str
    group: str
    date: str
    slides: tuple[NBSlide, ...]

    @classmethod
    def from_dict(cls, data: dict) -> "NBDeck":
        """Build an NBDeck from the JSON structure returned by the AI."""
        slides = tuple(
            NBSlide(
                kind=str(slide.get("kind", "concept")),
                title=str(slide.get("title", "")),
                subtitle=str(slide.get("subtitle", "")),
                items=tuple(str(item) for item in slide.get("items", [])),
                sections=tuple(
                    (str(heading), str(body))
                    for heading, body in slide.get("sections", [])
                ),
                terms=tuple(
                    (str(term), str(definition))
                    for term, definition in slide.get("terms", [])
                ),
                steps=tuple(
                    (str(heading), str(body))
                    for heading, body in slide.get("steps", [])
                ),
                timeline=tuple(
                    (str(stage), str(description))
                    for stage, description in slide.get("timeline", [])
                ),
                comparisons=tuple(
                    (str(label), tuple(str(item) for item in values))
                    for label, values in slide.get("comparisons", [])
                ),
                statistics=tuple(
                    (str(value), str(label))
                    for value, label in slide.get("statistics", [])
                ),
                highlight=str(slide.get("highlight", "")),
                code=str(slide.get("code", "")),
            )
            for slide in data.get("slides", [])
        )
        return cls(
            title=str(data.get("title", "")),
            subject=str(data.get("subject", "")),
            teacher=str(data.get("teacher", "")),
            college=str(data.get("college", "")),
            group=str(data.get("group", "")),
            date=str(data.get("date", "")),
            slides=slides,
        )
