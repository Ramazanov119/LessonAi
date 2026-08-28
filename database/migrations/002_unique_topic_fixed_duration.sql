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
    existing_lesson_id uuid;
begin
    if current_user_id is null then
        raise exception 'AUTH_REQUIRED';
    end if;

    perform pg_advisory_xact_lock(hashtextextended(current_user_id::text, 0));

    select full_name, college
      into profile_name, profile_college
      from public.profiles
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
      from public.generation_events
     where user_id = current_user_id
       and event_date = public.edu_today();

    if existing_lesson_id is not null then
        return query select existing_lesson_id, today_count;
    end if;

    if today_count >= 8 then
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

    return query select existing_lesson_id, today_count + 1;
end;
$$;

grant execute on function public.create_lesson_with_daily_limit(
    text, text, text, integer, text, date, text, text, text, text
) to authenticated;

revoke execute on function public.create_lesson_with_daily_limit(
    text, text, text, integer, text, date, text, text, text, text
) from public, anon;