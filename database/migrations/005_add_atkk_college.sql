-- 005_add_atkk_college.sql

BEGIN;

ALTER TABLE public.profiles
DROP CONSTRAINT IF EXISTS profiles_college_check;

ALTER TABLE public.profiles
ADD CONSTRAINT profiles_college_check
CHECK (
    college IN (
        'ETEC',
        'META',
        'ALT',
        'Q',
        'ATKK'
    )
);

ALTER TABLE public.lessons
DROP CONSTRAINT IF EXISTS lessons_college_check;

ALTER TABLE public.lessons
ADD CONSTRAINT lessons_college_check
CHECK (
    college IN (
        'ETEC',
        'META',
        'ALT',
        'Q',
        'ATKK'
    )
);

COMMIT;