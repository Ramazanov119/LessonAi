"""Preflight the Word document before atomically saving a completed lesson plan."""
import json
import uuid
from dataclasses import dataclass, field

from services.docx_generator import build_doc
from services.lesson_validation import parse_lesson, normalize_meta_lesson, lesson_date_value


def generate_lesson_plan(service, generator, *args, operation_id=None, **kwargs):
    """Check storage before invoking any potentially paid content provider."""
    service.ensure_lesson_plan_storage(operation_id=operation_id)
    return generator(*args, **kwargs)


@dataclass(frozen=True)
class PendingLessonPlan:
    content: str
    metadata: object
    template_path: object
    existing_lesson_id: object = None
    operation_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self):
        object.__setattr__(self, 'content', json.dumps(parse_lesson(self.content), ensure_ascii=False))

    def save(self, service):
        return save_generated_lesson_plan(service, self.content, self.metadata, self.template_path,
                                         existing_lesson_id=self.existing_lesson_id, operation_id=self.operation_id)


def prepare_lesson_plan(content, metadata, template_path, *, operation_id=None):
    """Offline normalization and Word export; no provider or database calls."""
    operation_id = operation_id or str(uuid.uuid4())
    payload = parse_lesson(content)
    if metadata.college.upper() == 'META':
        already_canonical = payload.get('meta_schema_version') == 1
        try:
            payload = normalize_meta_lesson(payload, language=metadata.language,
                                            lesson_type=metadata.lesson_type, lesson_date=metadata.lesson_date)
            if not already_canonical:
                payload['meta_attempt_id'] = uuid.UUID(operation_id).hex
        except Exception as error:
            from services.meta_diagnostics import record_meta_failure
            record_meta_failure(payload, error, 'normalization')
            raise
    selected_date = lesson_date_value(metadata.lesson_date).isoformat()
    payload.update(date=selected_date, data=selected_date, lesson_date=selected_date)
    fields = {
        'topic': metadata.topic, 'subject': metadata.subject, 'teacher': metadata.full_name,
        'date': metadata.lesson_date, 'course': metadata.course, 'group': metadata.group_name,
        'lesson_type': metadata.lesson_type, 'language': metadata.language,
    }
    # Any validation/export exception leaves database/quota entirely untouched.
    try:
        document = build_doc('План урока', payload, template_path=template_path,
                             fields=fields, college=metadata.college)
    except Exception as error:
        if metadata.college.upper() == 'META':
            from services.meta_diagnostics import record_meta_failure
            record_meta_failure(payload, error, 'docx')
        raise
    serialized = json.dumps(payload, ensure_ascii=False)
    return document, serialized


def save_generated_lesson_plan(service, content, metadata, template_path, *, existing_lesson_id=None, operation_id=None):
    operation_id = operation_id or str(uuid.uuid4())
    service.ensure_lesson_plan_storage(operation_id=operation_id)
    document, serialized = prepare_lesson_plan(content, metadata, template_path, operation_id=operation_id)
    try:
        saved = service.save_lesson_plan(metadata, serialized, existing_lesson_id=existing_lesson_id, operation_id=operation_id)
    except Exception as error:
        if metadata.college.upper() == 'META':
            from services.meta_diagnostics import record_meta_failure
            record_meta_failure(serialized, error, 'save')
        raise
    return document, saved
