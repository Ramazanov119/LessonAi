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

COMMIT;
