-- Read-only inventory before reviewing/applying 006. Save output privately.
SELECT p.oid::regprocedure AS signature, pg_get_userbyid(p.proowner) AS owner,
 p.prosecdef AS security_definer, p.proacl, pg_get_functiondef(p.oid) AS definition
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='public' AND p.prokind='f'
ORDER BY 1;
SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check
FROM pg_policies WHERE schemaname IN ('public','storage') ORDER BY tablename,policyname;
SELECT table_schema,table_name,grantee,privilege_type FROM information_schema.role_table_grants
WHERE table_schema='public' AND grantee IN ('anon','authenticated') ORDER BY table_name,grantee;
SELECT count(*) AS existing_auth_users FROM auth.users;
SELECT count(*) AS existing_lessons FROM public.lessons;
SELECT count(*) AS existing_materials FROM public.lesson_materials;
