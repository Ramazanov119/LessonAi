-- Metadata only: safe in SQL Editor; no documents, profiles or quota rows are read/written.
BEGIN TRANSACTION READ ONLY;
SELECT p.proname, pg_get_function_arguments(p.oid) AS arguments,
       pg_get_function_result(p.oid) AS result, p.prosecdef AS security_definer,
       has_function_privilege('authenticated', p.oid, 'EXECUTE') AS authenticated_can_execute
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public' AND p.proname IN (
    'save_lesson_plan_with_daily_limit', 'lesson_plan_storage_status',
    'create_lesson_with_daily_limit', 'edu_today'
);
SELECT c.relname AS table_name, c.relrowsecurity AS rls_enabled,
       k.conname AS constraint_name, pg_get_constraintdef(k.oid) AS definition
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_constraint k ON k.conrelid = c.oid
WHERE n.nspname = 'public' AND c.relname IN (
    'profiles', 'lessons', 'generation_events', 'lesson_materials', 'lesson_plan_operations'
);
SELECT table_name, column_name, udt_name
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name IN (
    'profiles', 'lessons', 'generation_events', 'lesson_materials', 'lesson_plan_operations'
)
ORDER BY table_name, ordinal_position;
ROLLBACK;
