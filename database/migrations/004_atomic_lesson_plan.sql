-- Apply manually after reviewing on an isolated database. No production execution by Codex.
-- Version 2: atomic save, per-user idempotency, read-only readiness probe.
-- Existing production RPC: export its definition/owner/ACL and inspect all overloads first.
-- This migration retires the reviewed 12-argument API: drain old clients before applying.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

-- Fail before DDL for unreviewed identities or names. Do not DROP an unknown function.
DO $$
DECLARE
    existing record;
    legacy_oid oid := to_regprocedure('public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid)');
    target_oid oid := to_regprocedure('public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid)');
    input_names text[] := ARRAY['p_subject','p_topic','p_group_name','p_course','p_duration','p_lesson_date','p_language','p_lesson_type','p_speciality','p_chair','p_material_content'];
BEGIN
    FOR existing IN SELECT p.* FROM pg_catalog.pg_proc p
                    JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = 'public' AND p.proname = 'save_lesson_plan_with_daily_limit'
    LOOP
        IF existing.oid IS DISTINCT FROM legacy_oid AND existing.oid IS DISTINCT FROM target_oid THEN
            RAISE EXCEPTION 'UNREVIEWED_SAVE_RPC_OVERLOAD';
        END IF;
        IF NOT existing.prosecdef OR NOT existing.proretset
           OR pg_catalog.pg_get_function_result(existing.oid) <> 'TABLE(lesson_id uuid, daily_count integer)' THEN
            RAISE EXCEPTION 'SAVE_RPC_RESULT_OR_SECURITY_REVIEW_REQUIRED';
        END IF;
        IF existing.oid = legacy_oid THEN
            IF existing.proargnames[1:12] IS DISTINCT FROM input_names || ARRAY['p_existing_lesson_id'] THEN
                RAISE EXCEPTION 'LEGACY_SAVE_RPC_ARGUMENT_REVIEW_REQUIRED';
            END IF;
        ELSE
            IF existing.proargnames[1:13] IS DISTINCT FROM input_names || ARRAY['p_operation_id','p_existing_lesson_id']
               OR existing.pronargdefaults > 1 THEN
                RAISE EXCEPTION 'TARGET_SAVE_RPC_ARGUMENT_REVIEW_REQUIRED';
            END IF;
        END IF;
    END LOOP;
END;
$$;

CREATE TABLE IF NOT EXISTS public.lesson_plan_operations (
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    operation_id uuid NOT NULL,
    request_hash text NOT NULL,
    lesson_id uuid REFERENCES public.lessons(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, operation_id)
);
ALTER TABLE public.lesson_plan_operations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.lesson_plan_operations FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.save_lesson_plan_with_daily_limit(
    p_subject text,
    p_topic text,
    p_group_name text,
    p_course integer,
    p_duration text,
    p_lesson_date date,
    p_language text,
    p_lesson_type text,
    p_speciality text,
    p_chair text,
    p_material_content text,
    p_operation_id uuid,
    p_existing_lesson_id uuid DEFAULT NULL
)
RETURNS TABLE (lesson_id uuid, daily_count integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
#variable_conflict use_column
DECLARE
    current_user_id uuid := auth.uid();
    result_id uuid;
    result_count integer;
    request_fingerprint text;
    previous public.lesson_plan_operations%ROWTYPE;
    material jsonb;
BEGIN
    IF current_user_id IS NULL THEN RAISE EXCEPTION 'AUTH_REQUIRED'; END IF;
    IF p_operation_id IS NULL THEN RAISE EXCEPTION 'OPERATION_ID_REQUIRED'; END IF;
    material := p_material_content::jsonb;
    IF material IS NULL OR jsonb_typeof(material) <> 'object' OR material = '{}'::jsonb THEN
        RAISE EXCEPTION 'INVALID_MATERIAL_CONTENT';
    END IF;
    request_fingerprint := md5(jsonb_build_object(
        'subject', p_subject, 'topic', p_topic, 'group_name', p_group_name,
        'course', p_course, 'duration', p_duration, 'lesson_date', p_lesson_date,
        'language', p_language, 'lesson_type', p_lesson_type,
        'speciality', p_speciality, 'chair', p_chair,
        'content', material, 'existing_lesson_id', p_existing_lesson_id
    )::text);
    -- Same lock as the existing creation RPC: serialize quota and concurrent retries.
    PERFORM pg_advisory_xact_lock(hashtextextended(current_user_id::text, 0));
    SELECT op.* INTO previous FROM public.lesson_plan_operations op
     WHERE op.user_id = current_user_id AND op.operation_id = p_operation_id;
    IF FOUND THEN
        IF previous.request_hash <> request_fingerprint THEN RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT'; END IF;
        SELECT l.id INTO result_id FROM public.lessons l
         WHERE l.id = previous.lesson_id AND l.user_id = current_user_id;
        IF result_id IS NULL THEN RAISE EXCEPTION 'LESSON_NOT_FOUND'; END IF;
        SELECT count(*)::integer INTO result_count FROM public.generation_events e
         WHERE e.user_id = current_user_id AND e.event_date = public.edu_today();
        RETURN QUERY SELECT result_id, result_count;
        RETURN;
    END IF;
    IF p_existing_lesson_id IS NULL THEN
        SELECT created.lesson_id, created.daily_count INTO result_id, result_count
          FROM public.create_lesson_with_daily_limit(
              p_subject, p_topic, p_group_name, p_course, p_duration,
              p_lesson_date, p_language, p_lesson_type, p_speciality, p_chair
          ) AS created;
    ELSE
        SELECT l.id INTO result_id FROM public.lessons l
         WHERE l.id = p_existing_lesson_id AND l.user_id = current_user_id FOR UPDATE;
        IF result_id IS NULL THEN RAISE EXCEPTION 'LESSON_NOT_FOUND'; END IF;
        SELECT count(*)::integer INTO result_count FROM public.generation_events e
         WHERE e.user_id = current_user_id AND e.event_date = public.edu_today();
    END IF;
    IF result_id IS NULL THEN RAISE EXCEPTION 'LESSON_NOT_FOUND'; END IF;
    INSERT INTO public.lesson_materials AS m (lesson_id, material_type, content)
    VALUES (result_id, 'lesson_plan', p_material_content)
    ON CONFLICT (lesson_id, material_type) DO UPDATE
        SET content = EXCLUDED.content, updated_at = now();
    INSERT INTO public.lesson_plan_operations(user_id, operation_id, request_hash, lesson_id)
    VALUES (current_user_id, p_operation_id, request_fingerprint, result_id);
    -- Any exception rolls back the lesson, quota event, material and operation together.
    RETURN QUERY SELECT result_id, result_count;
END;
$$;
REVOKE EXECUTE ON FUNCTION public.save_lesson_plan_with_daily_limit(
    text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid
) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.save_lesson_plan_with_daily_limit(
    text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid
) TO authenticated;
-- Retire the earlier 12-argument overload if a test/staging instance already has it.
-- No CASCADE: external dependencies cause a rollback and require review instead.
DROP FUNCTION IF EXISTS public.save_lesson_plan_with_daily_limit(
    text,text,text,integer,text,date,text,text,text,text,text,uuid
);

CREATE OR REPLACE FUNCTION public.lesson_plan_storage_status()
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    save_oid oid := to_regprocedure('public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid)');
    create_oid oid := to_regprocedure('public.create_lesson_with_daily_limit(text,text,text,integer,text,date,text,text,text,text)');
    reasons text[] := ARRAY[]::text[];
    definition text;
    save_owner oid;
    create_owner oid;
    table_name text;
    college_name text;
BEGIN
    IF auth.uid() IS NULL THEN RAISE EXCEPTION 'AUTH_REQUIRED'; END IF;
    IF save_oid IS NULL THEN
        reasons := array_append(reasons, 'missing_save_rpc');
    ELSIF NOT has_function_privilege('authenticated', save_oid, 'EXECUTE') THEN
        reasons := array_append(reasons, 'save_rpc_permission');
    ELSIF NOT EXISTS (SELECT 1 FROM pg_proc p WHERE p.oid = save_oid
                      AND p.prosecdef AND p.proretset
                      AND p.proargnames[1:13] = ARRAY['p_subject','p_topic','p_group_name','p_course','p_duration','p_lesson_date','p_language','p_lesson_type','p_speciality','p_chair','p_material_content','p_operation_id','p_existing_lesson_id']) THEN
        reasons := array_append(reasons, 'save_rpc_contract');
    END IF;
    IF create_oid IS NULL OR to_regprocedure('public.edu_today()') IS NULL THEN
        reasons := array_append(reasons, 'missing_creation_rpc');
    ELSIF NOT EXISTS (SELECT 1 FROM pg_proc WHERE oid = create_oid AND prosecdef AND proretset
                      AND proargnames[11:12] = ARRAY['lesson_id','daily_count']) THEN
        reasons := array_append(reasons, 'creation_rpc_contract');
    END IF;
    IF EXISTS (
        SELECT 1 FROM (VALUES
            ('profiles','id','uuid'), ('profiles','full_name','text'), ('profiles','college','text'),
            ('lessons','id','uuid'), ('lessons','user_id','uuid'), ('lessons','full_name','text'), ('lessons','college','text'),
            ('lessons','subject','text'), ('lessons','topic','text'), ('lessons','group_name','text'), ('lessons','course','int4'),
            ('lessons','duration','text'), ('lessons','lesson_date','date'), ('lessons','language','text'),
            ('lessons','lesson_type','text'), ('lessons','speciality','text'), ('lessons','chair','text'), ('lessons','created_at','timestamptz'),
            ('generation_events','user_id','uuid'), ('generation_events','lesson_id','uuid'), ('generation_events','event_date','date'),
            ('lesson_materials','lesson_id','uuid'), ('lesson_materials','material_type','text'), ('lesson_materials','content','text'), ('lesson_materials','updated_at','timestamptz'),
            ('lesson_plan_operations','user_id','uuid'), ('lesson_plan_operations','operation_id','uuid'), ('lesson_plan_operations','request_hash','text'), ('lesson_plan_operations','lesson_id','uuid')
        ) AS expected(table_name,column_name,type_name)
        LEFT JOIN information_schema.columns c ON c.table_schema = 'public'
          AND c.table_name = expected.table_name AND c.column_name = expected.column_name
        WHERE c.udt_name IS DISTINCT FROM expected.type_name
    ) THEN reasons := array_append(reasons, 'table_contract'); END IF;
    SELECT proowner INTO save_owner FROM pg_proc WHERE oid = save_oid;
    IF save_owner IS NOT NULL AND EXISTS (
        SELECT 1 FROM (VALUES
            ('public.lessons','SELECT'), ('public.generation_events','SELECT'),
            ('public.lesson_materials','INSERT'), ('public.lesson_materials','UPDATE'),
            ('public.lesson_plan_operations','SELECT'), ('public.lesson_plan_operations','INSERT')
        ) AS required(table_name,privilege_name)
        WHERE NOT coalesce(has_table_privilege(save_owner, to_regclass(required.table_name), required.privilege_name), false)
    ) THEN reasons := array_append(reasons, 'function_owner_permissions'); END IF;
    IF save_owner IS NOT NULL AND create_oid IS NOT NULL
       AND NOT has_function_privilege(save_owner, create_oid, 'EXECUTE') THEN
        reasons := array_append(reasons, 'creation_rpc_permission');
    END IF;
    SELECT proowner INTO create_owner FROM pg_proc WHERE oid = create_oid;
    IF create_owner IS NOT NULL AND EXISTS (
        SELECT 1 FROM (VALUES
            ('public.profiles','SELECT'), ('public.lessons','SELECT'), ('public.lessons','INSERT'),
            ('public.generation_events','SELECT'), ('public.generation_events','INSERT')
        ) AS required(table_name,privilege_name)
        WHERE NOT coalesce(has_table_privilege(create_owner, to_regclass(required.table_name), required.privilege_name), false)
    ) THEN reasons := array_append(reasons, 'creation_owner_permissions'); END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_class WHERE oid = to_regclass('public.lesson_plan_operations') AND relrowsecurity)
       OR coalesce(has_table_privilege('authenticated', to_regclass('public.lesson_plan_operations'), 'INSERT'), false) THEN
        reasons := array_append(reasons, 'operation_table_access');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c WHERE c.conrelid = to_regclass('public.lesson_materials')
         AND c.contype IN ('u','p') AND c.convalidated
         AND c.conkey = ARRAY[
             (SELECT attnum FROM pg_attribute WHERE attrelid = c.conrelid AND attname = 'lesson_id'),
             (SELECT attnum FROM pg_attribute WHERE attrelid = c.conrelid AND attname = 'material_type')
         ]::smallint[]
    ) THEN reasons := array_append(reasons, 'material_unique_constraint'); END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conrelid = to_regclass('public.lesson_plan_operations')
                   AND c.contype = 'p' AND c.conkey = ARRAY[
                     (SELECT attnum FROM pg_attribute WHERE attrelid = c.conrelid AND attname = 'user_id'),
                     (SELECT attnum FROM pg_attribute WHERE attrelid = c.conrelid AND attname = 'operation_id')
                   ]::smallint[]) THEN reasons := array_append(reasons, 'operation_primary_key'); END IF;
    -- Recognize the project's explicit allow-list CHECKs; unknown variants require review.
    FOREACH table_name IN ARRAY ARRAY['profiles','lessons'] LOOP
        SELECT string_agg(pg_get_constraintdef(c.oid), ' ') INTO definition
          FROM pg_constraint c WHERE c.conrelid = to_regclass('public.' || table_name)
           AND c.contype = 'c' AND c.conname = table_name || '_college_check';
        FOREACH college_name IN ARRAY ARRAY['ETEC','META','ALT','Q','ATKK'] LOOP
            IF definition IS NULL OR position(quote_literal(college_name) IN definition) = 0 THEN
                reasons := array_append(reasons, 'college_constraints'); EXIT;
            END IF;
        END LOOP;
    END LOOP;
    RETURN jsonb_build_object('api_version', 2, 'ready', cardinality(reasons) = 0, 'reasons', reasons);
END;
$$;
REVOKE EXECUTE ON FUNCTION public.lesson_plan_storage_status() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.lesson_plan_storage_status() TO authenticated;
NOTIFY pgrst, 'reload schema';
COMMIT;
