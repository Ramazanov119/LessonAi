-- Apply after 006_subscriptions.sql on a database with public.generation_logs.
-- Generation admission belongs to PlatformAccess: count < daily_limit_v1.
-- LessonAi records the successful AI call BEFORE saving the document. Storage
-- therefore accepts count == limit (the final allowed generation is already logged).
-- It does not consume a second generation and preserves atomic/idempotent saves.
-- generation_events remains historical lesson-storage bookkeeping only.
BEGIN;
create or replace function public.create_lesson_with_daily_limit(
    p_subject text,
    p_topic text,
    p_group_name text,
    p_course integer,
    p_duration text,
    p_lesson_date date,
    p_language text,
    p_lesson_type text,
    p_speciality text,
    p_chair text
)
returns table (lesson_id uuid, daily_count integer)
language plpgsql
security definer
set search_path = public
as $$
declare
    current_user_id uuid := auth.uid();
    profile_name text;
    profile_college text;
    today_count integer;
    profile_limit integer;
    day_start timestamptz := date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    existing_lesson_id uuid;
BEGIN
    PERFORM public.require_subscription_access();
    if current_user_id is null then
        raise exception 'AUTH_REQUIRED';
    end if;

    perform pg_advisory_xact_lock(hashtextextended(current_user_id::text, 0));

    select full_name, college, coalesce((to_jsonb(p)->>'daily_limit_v1')::integer, 10)
      into profile_name, profile_college, profile_limit
      from public.profiles p
     where id = current_user_id;

    if profile_name is null or profile_college is null then
        raise exception 'PROFILE_REQUIRED';
    end if;

    select l.id
      into existing_lesson_id
      from public.lessons l
     where l.user_id = current_user_id
       and l.lesson_date = p_lesson_date
       and lower(trim(l.topic)) = lower(trim(p_topic))
     order by l.created_at
     limit 1;

    select count(*)::integer
      into today_count
      from public.generation_logs
     where user_id = current_user_id
       and status = 'success'
       and created_at >= day_start
       and created_at < day_start + interval '1 day';

    if existing_lesson_id is not null then
        return query select existing_lesson_id, today_count;
    end if;

    if profile_limit <= 0 or today_count > profile_limit then
        raise exception 'DAILY_LIMIT_REACHED';
    end if;

    insert into public.lessons (
        user_id, full_name, college, subject, topic, group_name, course,
        duration, lesson_date, language, lesson_type, speciality, chair
    ) values (
        current_user_id, profile_name, profile_college, p_subject, p_topic,
        p_group_name, p_course, '70 минут', p_lesson_date, p_language,
        p_lesson_type, p_speciality, p_chair
    )
    returning id into existing_lesson_id;

    insert into public.generation_events (user_id, lesson_id, event_date)
    values (current_user_id, existing_lesson_id, public.edu_today());

    return query select existing_lesson_id, today_count;
end;
$$;

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
    PERFORM public.require_subscription_access();
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

-- CREATE OR REPLACE preserves existing ACLs, but a prior installation may have
-- revoked EXECUTE. Restore the exact PostgREST contracts explicitly.
REVOKE EXECUTE ON FUNCTION public.create_lesson_with_daily_limit(
    text,text,text,integer,text,date,text,text,text,text
) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.create_lesson_with_daily_limit(
    text,text,text,integer,text,date,text,text,text,text
) TO authenticated;
REVOKE EXECUTE ON FUNCTION public.save_lesson_plan_with_daily_limit(
    text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid
) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.save_lesson_plan_with_daily_limit(
    text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid
) TO authenticated;
NOTIFY pgrst, 'reload schema';
COMMIT;
