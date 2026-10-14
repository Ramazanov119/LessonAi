-- READ ONLY export. Save results privately outside Git BEFORE any migration.
-- Function bodies may contain deployment-specific literals: do not paste secrets into chat.
BEGIN TRANSACTION READ ONLY;
SELECT p.oid::regprocedure::text AS identity,
       pg_get_functiondef(p.oid) AS definition_sql,
       format('ALTER FUNCTION %I.%I(%s) OWNER TO %I;', n.nspname, p.proname,
              pg_get_function_identity_arguments(p.oid), pg_get_userbyid(p.proowner)) AS restore_owner_sql,
       obj_description(p.oid, 'pg_proc') AS original_comment,
       p.proacl::text AS explicit_acl,
       p.proconfig AS settings
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public' AND p.proname IN (
    'save_lesson_plan_with_daily_limit', 'lesson_plan_storage_status',
    'create_lesson_with_daily_limit', 'edu_today'
)
ORDER BY p.proname, p.oid;

-- pg_get_functiondef alone does NOT back up owner and GRANTs.
SELECT p.oid::regprocedure::text AS identity,
       CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END AS grantee,
       pg_get_userbyid(a.grantor) AS grantor, a.privilege_type, a.is_grantable,
       format('GRANT %s ON FUNCTION %I.%I(%s) TO %s%s;',
              a.privilege_type, n.nspname, p.proname, pg_get_function_identity_arguments(p.oid),
              CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE quote_ident(pg_get_userbyid(a.grantee)) END,
              CASE WHEN a.is_grantable THEN ' WITH GRANT OPTION' ELSE '' END) AS grant_sql
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
CROSS JOIN LATERAL aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
WHERE n.nspname = 'public' AND p.proname IN (
    'save_lesson_plan_with_daily_limit', 'lesson_plan_storage_status',
    'create_lesson_with_daily_limit', 'edu_today'
)
ORDER BY p.proname, p.oid, grantee;
ROLLBACK;
