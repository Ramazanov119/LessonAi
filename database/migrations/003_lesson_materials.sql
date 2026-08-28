create table if not exists public.lesson_materials (
    id uuid primary key default gen_random_uuid(),
    lesson_id uuid not null references public.lessons(id) on delete cascade,
    material_type text not null check (material_type in (
        'lesson_plan', 'lecture', 'practice', 'presentation'
    )),
    content text not null check (length(trim(content)) > 0),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (lesson_id, material_type)
);

create index if not exists lesson_materials_lesson_idx
    on public.lesson_materials (lesson_id, material_type);

alter table public.lesson_materials enable row level security;

revoke all on public.lesson_materials from anon, authenticated;
grant select, insert, update on public.lesson_materials to authenticated;

drop policy if exists lesson_materials_select_own on public.lesson_materials;
drop policy if exists lesson_materials_insert_own on public.lesson_materials;
drop policy if exists lesson_materials_update_own on public.lesson_materials;

create policy lesson_materials_select_own
    on public.lesson_materials for select
    to authenticated
    using (
        exists (
            select 1 from public.lessons
            where lessons.id = lesson_materials.lesson_id
              and lessons.user_id = auth.uid()
        )
    );

create policy lesson_materials_insert_own
    on public.lesson_materials for insert
    to authenticated
    with check (
        exists (
            select 1 from public.lessons
            where lessons.id = lesson_materials.lesson_id
              and lessons.user_id = auth.uid()
        )
    );

create policy lesson_materials_update_own
    on public.lesson_materials for update
    to authenticated
    using (
        exists (
            select 1 from public.lessons
            where lessons.id = lesson_materials.lesson_id
              and lessons.user_id = auth.uid()
        )
    )
    with check (
        exists (
            select 1 from public.lessons
            where lessons.id = lesson_materials.lesson_id
              and lessons.user_id = auth.uid()
        )
    );

create or replace function public.set_lesson_material_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists lesson_materials_updated_at on public.lesson_materials;
create trigger lesson_materials_updated_at
    before update on public.lesson_materials
    for each row execute procedure public.set_lesson_material_updated_at();
