-- READ ONLY. Run each SELECT separately if SQL Editor displays only the last result.
BEGIN TRANSACTION READ ONLY;
SELECT current_database() AS database_name, current_user AS migration_role,
       current_setting('server_version') AS postgres_version;

-- Every overload, not only the first function with this name.
SELECT p.oid, p.oid::regprocedure::text AS identity,
       p.pronargs AS input_count, p.pronargdefaults AS default_count,
       pg_get_function_arguments(p.oid) AS full_arguments,
       p.proargnames AS argument_names, p.proargmodes AS argument_modes,
       pg_get_function_result(p.oid) AS result,
       pg_get_userbyid(p.proowner) AS owner,
       p.prosecdef AS security_definer, p.proconfig AS settings,
       has_function_privilege('authenticated', p.oid, 'EXECUTE') AS authenticated_execute,
       has_function_privilege('anon', p.oid, 'EXECUTE') AS anon_execute,
       EXISTS (SELECT 1 FROM aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
               WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE') AS public_execute
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public' AND p.proname IN (
    'save_lesson_plan_with_daily_limit', 'lesson_plan_storage_status',
    'create_lesson_with_daily_limit', 'edu_today'
)
ORDER BY p.proname, p.oid;

-- Recorded incoming dependencies: no CASCADE is used by the migration.
-- Dynamic SQL, string-body PL/pgSQL calls and external application clients may not appear here.
SELECT p.oid::regprocedure::text AS referenced_function, d.deptype,
       pg_describe_object(d.classid, d.objid, d.objsubid) AS dependent_object
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
JOIN pg_depend d ON d.refclassid = 'pg_proc'::regclass AND d.refobjid = p.oid
WHERE n.nspname = 'public' AND p.proname = 'save_lesson_plan_with_daily_limit'
ORDER BY 1, 3;

SELECT has_schema_privilege('authenticated', 'public', 'CREATE') AS authenticated_public_create,
       has_schema_privilege('anon', 'public', 'CREATE') AS anon_public_create;
ROLLBACK;
