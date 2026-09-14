-- =========================================================
-- 004_add_alt_college.sql
-- Добавление новых колледжей: ALT и Q
-- =========================================================


-- =========================================================
-- PROFILES
-- =========================================================

alter table public.profiles
drop constraint if exists profiles_college_check;

alter table public.profiles
add constraint profiles_college_check
check (college in ('ETEC', 'META', 'ALT', 'Q'));


-- =========================================================
-- LESSONS
-- =========================================================

alter table public.lessons
drop constraint if exists lessons_college_check;

alter table public.lessons
add constraint lessons_college_check
check (college in ('ETEC', 'META', 'ALT', 'Q'));