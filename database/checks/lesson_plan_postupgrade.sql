-- READ ONLY metadata checks. Does not call the mutating save RPC.
BEGIN TRANSACTION READ ONLY;
WITH functions AS (
    SELECT p.*, n.nspname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public' AND p.proname IN ('save_lesson_plan_with_daily_limit','lesson_plan_storage_status')
)
SELECT oid::regprocedure::text AS identity, pg_get_function_arguments(oid) AS full_arguments,
       pg_get_function_result(oid) AS result, pg_get_userbyid(proowner) AS owner,
       prosecdef AS security_definer, proconfig AS settings,
       has_function_privilege('authenticated', oid, 'EXECUTE') AS authenticated_execute,
       has_function_privilege('anon', oid, 'EXECUTE') AS anon_execute,
       EXISTS (SELECT 1 FROM aclexplode(coalesce(proacl, acldefault('f', proowner))) a
               WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE') AS public_execute
FROM functions ORDER BY proname, oid;
SELECT to_regprocedure('public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid)') IS NULL AS legacy_12_removed,
       to_regprocedure('public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid)') IS NOT NULL AS target_13_exists,
       to_regprocedure('public.lesson_plan_storage_status()') IS NOT NULL AS readiness_exists;
SELECT c.relrowsecurity AS operations_rls,
       has_table_privilege('authenticated', c.oid, 'INSERT') AS authenticated_direct_insert,
       has_table_privilege('anon', c.oid, 'INSERT') AS anon_direct_insert
FROM pg_class c WHERE c.oid = to_regclass('public.lesson_plan_operations');
ROLLBACK;
