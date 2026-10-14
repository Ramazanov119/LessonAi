"""Allow-listed database failure metadata; never log server text or parameters."""
import logging
import os
import re
import uuid


def database_failure(error, rpc, phase, operation_id, schema_reasons=None):
    raw_code = getattr(error, 'code', None)
    if raw_code is None:
        match = re.search(r'\b(PGRST\d{3}|[0-9]{2}[0-9A-Z]{3})\b', str(error))
        raw_code = match.group(1) if match else None
    code = raw_code if isinstance(raw_code, str) and re.fullmatch(r'PGRST\d{3}|(?:[0-9]{2}|P0|XX|HV|F0)[0-9A-Z]{3}', raw_code) else 'UNKNOWN'
    reason = {'PGRST202': 'rpc_missing_or_signature', 'PGRST203': 'rpc_ambiguous',
              '42883': 'rpc_missing_or_signature', '42501': 'permission_denied',
              '23514': 'constraint_violation', '23503': 'foreign_key_violation',
              '22P02': 'invalid_parameter', '42702': 'ambiguous_sql_reference',
              'PGRST301': 'authentication_failed'}.get(code, 'database_or_transport_error')
    if type(error).__name__ == 'DatabaseCompatibilityError':
        reason = 'incompatible_schema'
    # Only fixed application exceptions are retained. No free-form PostgreSQL details.
    for token in ('DAILY_LIMIT_REACHED', 'AUTH_REQUIRED', 'PROFILE_REQUIRED', 'LESSON_NOT_FOUND',
                  'IDEMPOTENCY_CONFLICT', 'OPERATION_ID_REQUIRED', 'INVALID_MATERIAL_CONTENT'):
        if re.search(r'\b' + token + r'\b', str(error)):
            reason = token.lower()
            break
    try:
        operation_id = str(uuid.UUID(str(operation_id)))
    except (ValueError, TypeError):
        operation_id = 'invalid_operation_id'
    details = {'rpc': rpc if rpc in ('lesson_plan_storage_status', 'save_lesson_plan_with_daily_limit') else 'unknown_rpc',
               'code': code, 'reason': reason, 'phase': phase if phase in ('database_preflight', 'save') else 'unknown_phase', 'operation_id': operation_id}
    allowed = {'missing_save_rpc', 'save_rpc_permission', 'save_rpc_contract', 'missing_creation_rpc',
               'creation_rpc_contract', 'table_contract', 'function_owner_permissions', 'creation_rpc_permission',
               'creation_owner_permissions',
               'operation_table_access', 'material_unique_constraint', 'operation_primary_key', 'college_constraints'}
    if isinstance(schema_reasons, list):
        details['schema_reasons'] = [value for value in schema_reasons if isinstance(value, str) and value in allowed]
    if os.getenv('LESSONAI_ENV', '').lower() in ('local', 'development', 'test'):
        logging.getLogger(__name__).error('Lesson plan storage failure %s', details)
    return details
