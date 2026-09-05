create extension if not exists pgcrypto;

create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    full_name text not null check (length(trim(full_name)) > 0),
    college text not null check (college in ('ETEC', 'META')),
    created_at timestamptz not null default now(),
    role text not null default 'teacher',
    subscription_status text not null default 'pending',
    subscription_plan text null default 'standard',
    subscription_start timestamptz null,
    subscription_end timestamptz null,
    updated_at timestamptz null default now()
);

create table if not exists public.lessons (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    full_name text not null check (length(trim(full_name)) > 0),
    college text not null check (college in ('ETEC', 'META')),
    subject text not null check (length(trim(subject)) > 0),
    topic text not null check (length(trim(topic)) > 0),
    group_name text not null check (length(trim(group_name)) > 0),
    course integer not null check (course between 1 and 4),
    duration text not null check (length(trim(duration)) > 0),
    lesson_date date not null,
    language text not null check (length(trim(language)) > 0),
    lesson_type text not null check (length(trim(lesson_type)) > 0),
    speciality text not null check (length(trim(speciality)) > 0),
    chair text not null check (length(trim(chair)) > 0),
    created_at timestamptz not null default now()
);

create table if not exists public.generation_events (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    lesson_id uuid not null unique references public.lessons(id) on delete cascade,
    event_date date not null,
    created_at timestamptz not null default now()
);

create index if not exists lessons_user_created_idx
    on public.lessons (user_id, created_at desc);
create index if not exists generation_events_user_date_idx
    on public.generation_events (user_id, event_date);

alter table public.profiles enable row level security;
alter table public.lessons enable row level security;
alter table public.generation_events enable row level security;

create or replace function public.handle_new_user_profile()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (
        id,
        full_name,
        college,
        role,
        subscription_status,
        subscription_plan,
        updated_at
    )
    values (
        new.id,
        coalesce(new.raw_user_meta_data ->> 'full_name', new.email),
        coalesce(new.raw_user_meta_data ->> 'college', 'ETEC'),
        'teacher',
        'pending',
        'standard',
        now()
    )
    on conflict (id) do update
        set full_name = excluded.full_name,
            college = excluded.college,
            role = coalesce(public.profiles.role, 'teacher'),
            subscription_status = coalesce(public.profiles.subscription_status, 'pending'),
            subscription_plan = coalesce(public.profiles.subscription_plan, 'standard'),
            updated_at = now();

    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute procedure public.handle_new_user_profile();

drop policy if exists profiles_select_own on public.profiles;
drop policy if exists profiles_insert_own on public.profiles;
drop policy if exists profiles_update_own on public.profiles;
drop policy if exists lessons_select_own on public.lessons;
drop policy if exists lessons_insert_own on public.lessons;
drop policy if exists lessons_update_own on public.lessons;
drop policy if exists lessons_delete_own on public.lessons;

create policy profiles_select_own
    on public.profiles for select
    to authenticated
    using (id = auth.uid());

create policy profiles_insert_own
    on public.profiles for insert
    to authenticated
    with check (id = auth.uid());

create policy profiles_update_own
    on public.profiles for update
    to authenticated
    using (id = auth.uid())
    with check (id = auth.uid());

create policy lessons_select_own
    on public.lessons for select
    to authenticated
    using (user_id = auth.uid());

create policy lessons_insert_own
    on public.lessons for insert
    to authenticated
    with check (user_id = auth.uid());

create policy lessons_update_own
    on public.lessons for update
    to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());

create policy lessons_delete_own
    on public.lessons for delete
    to authenticated
    using (user_id = auth.uid());

revoke all on public.generation_events from anon, authenticated;
revoke insert on public.lessons from anon, authenticated;
grant select, update, delete on public.lessons to authenticated;
grant select, insert, update on public.profiles to authenticated;
grant usage on schema public to anon, authenticated;

create or replace function public.edu_today()
returns date
language sql
stable
as $$
    select (now() at time zone 'Asia/Almaty')::date;
$$;

create or replace function public.get_daily_lesson_count(p_lesson_date date default null)
returns integer
language sql
stable
security definer
set search_path = public
as $$
    select count(*)::integer
    from public.generation_events
    where user_id = auth.uid()
      and event_date = coalesce(p_lesson_date, public.edu_today());
$$;

grant execute on function public.get_daily_lesson_count(date) to authenticated;
revoke execute on function public.get_daily_lesson_count(date) from public, anon;

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
    inserted_lesson_id uuid;
begin
    if current_user_id is null then
        raise exception 'AUTH_REQUIRED';
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended(current_user_id::text, 0)
    );

    select full_name, college
      into profile_name, profile_college
      from public.profiles
     where id = current_user_id;

    if profile_name is null or profile_college is null then
        raise exception 'PROFILE_REQUIRED';
    end if;

    select count(*)::integer
      into today_count
      from public.generation_events
     where user_id = current_user_id
       and event_date = public.edu_today();

    if today_count >= 8 then
        raise exception 'DAILY_LIMIT_REACHED';
    end if;

    insert into public.lessons (
        user_id, full_name, college, subject, topic, group_name, course,
        duration, lesson_date, language, lesson_type, speciality, chair
    ) values (
        current_user_id, profile_name, profile_college, p_subject, p_topic,
        p_group_name, p_course, p_duration, p_lesson_date, p_language,
        p_lesson_type, p_speciality, p_chair
    )
    returning id into inserted_lesson_id;

    insert into public.generation_events (user_id, lesson_id, event_date)
    values (current_user_id, inserted_lesson_id, public.edu_today());

    return query select inserted_lesson_id, today_count + 1;
end;
$$;

grant execute on function public.create_lesson_with_daily_limit(
    text, text, text, integer, text, date, text, text, text, text
) to authenticated;
revoke execute on function public.create_lesson_with_daily_limit(
    text, text, text, integer, text, date, text, text, text, text
) from public, anon;
