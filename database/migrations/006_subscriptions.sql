-- Review and apply on staging first. Leaves enforcement OFF until owner activation.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
-- Fail on obsolete/unknown overloads rather than leave an unguarded RPC callable.
DO $$
DECLARE candidate record;
BEGIN
 IF to_regprocedure('public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid)') IS NULL
 OR to_regprocedure('public.create_lesson_with_daily_limit(text,text,text,integer,text,date,text,text,text,text)') IS NULL THEN
 RAISE EXCEPTION 'APPLY_AND_VERIFY_004_ATOMIC_LESSON_PLAN_FIRST'; END IF;
 FOR candidate IN SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='public' AND p.proname IN ('save_lesson_plan_with_daily_limit','create_lesson_with_daily_limit') LOOP
 IF candidate.oid NOT IN (
 'public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid)'::regprocedure,
 'public.create_lesson_with_daily_limit(text,text,text,integer,text,date,text,text,text,text)'::regprocedure
 ) THEN RAISE EXCEPTION 'UNREVIEWED_LESSON_RPC_OVERLOAD'; END IF;
 END LOOP;
END;
$$;
CREATE TABLE public.subscription_settings (
 id boolean PRIMARY KEY DEFAULT true CHECK (id), enforced boolean NOT NULL DEFAULT false
);
INSERT INTO public.subscription_settings(id) VALUES(true);
CREATE TABLE public.subscription_admins (
 user_id uuid PRIMARY KEY REFERENCES auth.users(id), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.subscriptions (
 user_id uuid PRIMARY KEY REFERENCES auth.users(id), plan text NOT NULL DEFAULT 'standard' CHECK(length(trim(plan)) > 0),
 starts_at timestamptz NOT NULL DEFAULT now(), ends_at timestamptz NOT NULL,
 suspended boolean NOT NULL DEFAULT false, reason text NOT NULL DEFAULT '',
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK(ends_at > starts_at)
);
CREATE TABLE public.payments (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES auth.users(id),
 amount_kzt numeric(12,2) NOT NULL CHECK(amount_kzt > 0), paid_at timestamptz NOT NULL,
 method text NOT NULL CHECK(length(trim(method)) > 0), comment text NOT NULL DEFAULT '',
 confirmed_by uuid NOT NULL REFERENCES auth.users(id), confirmed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.admin_audit_logs (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, actor_id uuid REFERENCES auth.users(id),
 user_id uuid REFERENCES auth.users(id), action text NOT NULL, old_values jsonb, new_values jsonb,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON public.admin_audit_logs(user_id, created_at DESC);
ALTER TABLE public.subscription_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.subscription_admins ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_audit_logs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.subscription_settings, public.subscription_admins, public.subscriptions,
 public.payments, public.admin_audit_logs FROM PUBLIC, anon, authenticated;

CREATE FUNCTION public.is_subscription_admin() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
 SELECT EXISTS(SELECT 1 FROM public.subscription_admins WHERE user_id = auth.uid());
$$;
CREATE FUNCTION public.subscription_access() RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
 SELECT jsonb_build_object(
 'user_id', auth.uid(), 'is_admin', public.is_subscription_admin(), 'enforced', cfg.enforced,
 'allowed', auth.uid() IS NOT NULL AND (NOT cfg.enforced OR
   (s.user_id IS NOT NULL AND NOT s.suspended AND now() >= s.starts_at AND now() < s.ends_at)),
 'status', CASE WHEN s.suspended THEN 'suspended' WHEN s.user_id IS NULL THEN 'missing'
 WHEN now() < s.starts_at THEN 'scheduled' WHEN now() >= s.ends_at THEN 'expired' ELSE 'active' END,
 'ends_at', s.ends_at, 'reason', s.reason, 'server_time', now())
 FROM public.subscription_settings cfg LEFT JOIN public.subscriptions s ON s.user_id = auth.uid()
 WHERE cfg.id;
$$;
CREATE FUNCTION public.has_subscription_access() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
 SELECT coalesce((public.subscription_access()->>'allowed')::boolean, false);
$$;
CREATE FUNCTION public.require_subscription_access() RETURNS void
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
 IF NOT public.has_subscription_access() THEN RAISE EXCEPTION 'SUBSCRIPTION_REQUIRED' USING ERRCODE = '42501'; END IF;
END;
$$;

-- Restrictive policies AND with existing ownership policies, including unknown permissive ones.
CREATE POLICY subscriptions_gate ON public.lessons AS RESTRICTIVE FOR ALL TO authenticated
 USING (public.has_subscription_access()) WITH CHECK (public.has_subscription_access());
CREATE POLICY subscriptions_gate ON public.lesson_materials AS RESTRICTIVE FOR ALL TO authenticated
 USING (public.has_subscription_access()) WITH CHECK (public.has_subscription_access());
-- Triggers also run inside SECURITY DEFINER RPCs that bypass RLS.
CREATE FUNCTION public.guard_paid_write() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
 PERFORM public.require_subscription_access();
 IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER subscription_guard BEFORE INSERT OR UPDATE OR DELETE ON public.lessons
 FOR EACH ROW EXECUTE FUNCTION public.guard_paid_write();
CREATE TRIGGER subscription_guard BEFORE INSERT OR UPDATE OR DELETE ON public.lesson_materials
 FOR EACH ROW EXECUTE FUNCTION public.guard_paid_write();
CREATE TRIGGER subscription_guard BEFORE INSERT OR UPDATE OR DELETE ON public.generation_events
 FOR EACH ROW EXECUTE FUNCTION public.guard_paid_write();

CREATE FUNCTION public.admin_subscription_users() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
 IF NOT public.is_subscription_admin() THEN RAISE EXCEPTION 'ADMIN_REQUIRED' USING ERRCODE = '42501'; END IF;
 RETURN coalesce((SELECT jsonb_agg(to_jsonb(t) ORDER BY t.email) FROM (
 SELECT u.id AS user_id, coalesce(u.email, '') AS email, coalesce(p.full_name, '') AS full_name, coalesce(p.college, '') AS college,
 s.plan, s.starts_at, s.ends_at, coalesce(s.suspended,false) AS suspended, s.reason,
 CASE WHEN s.suspended THEN 'suspended' WHEN s.user_id IS NULL THEN 'missing'
 WHEN now() < s.starts_at THEN 'scheduled' WHEN now() >= s.ends_at THEN 'expired'
 WHEN s.ends_at <= now() + interval '7 days' THEN 'expiring' ELSE 'active' END AS status,
 CASE WHEN s.ends_at IS NULL THEN NULL ELSE ceil(extract(epoch FROM (s.ends_at-now()))/86400)::integer END AS days_left
 FROM auth.users u LEFT JOIN public.profiles p ON p.id=u.id
 LEFT JOIN public.subscriptions s ON s.user_id=u.id
 ) t), '[]'::jsonb);
END;
$$;
CREATE FUNCTION public.admin_change_subscription(p_user_id uuid, p_action text,
 p_days integer DEFAULT NULL, p_ends_at timestamptz DEFAULT NULL, p_reason text DEFAULT '', p_plan text DEFAULT 'standard')
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE previous jsonb; updated jsonb; finish timestamptz;
BEGIN
 IF NOT public.is_subscription_admin() THEN RAISE EXCEPTION 'ADMIN_REQUIRED' USING ERRCODE = '42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text, 1));
 SELECT to_jsonb(s) INTO previous FROM public.subscriptions s WHERE user_id=p_user_id FOR UPDATE;
 IF p_action IN ('extend','set_end') THEN
   IF p_action='extend' THEN
     IF p_days IS NULL OR p_days NOT IN (7,30,90,365) THEN RAISE EXCEPTION 'INVALID_DAYS'; END IF;
     finish := greatest(now(), (previous->>'ends_at')::timestamptz) + make_interval(days=>p_days);
   ELSE finish := p_ends_at; END IF;
   IF finish IS NULL THEN RAISE EXCEPTION 'END_REQUIRED'; END IF;
   INSERT INTO public.subscriptions(user_id,plan,starts_at,ends_at,reason)
   VALUES(p_user_id,p_plan,least(now(),finish-interval '1 microsecond'),finish,p_reason)
   ON CONFLICT(user_id) DO UPDATE SET ends_at=finish, starts_at=least(subscriptions.starts_at,now(),finish-interval '1 microsecond'),
     plan=p_plan, reason=p_reason, updated_at=now();
 ELSIF p_action IN ('suspend','resume') THEN
   IF p_action='suspend' AND p_user_id=auth.uid() THEN RAISE EXCEPTION 'SELF_SUSPENSION_FORBIDDEN'; END IF;
   IF previous IS NULL THEN RAISE EXCEPTION 'SUBSCRIPTION_NOT_FOUND'; END IF;
   IF p_action='suspend' AND length(trim(p_reason))=0 THEN RAISE EXCEPTION 'REASON_REQUIRED'; END IF;
   UPDATE public.subscriptions SET suspended=(p_action='suspend'), reason=p_reason, updated_at=now() WHERE user_id=p_user_id;
 ELSE RAISE EXCEPTION 'INVALID_ACTION'; END IF;
 SELECT to_jsonb(s) INTO updated FROM public.subscriptions s WHERE user_id=p_user_id;
 INSERT INTO public.admin_audit_logs(actor_id,user_id,action,old_values,new_values)
 VALUES(auth.uid(),p_user_id,p_action,previous,updated);
END;
$$;
CREATE FUNCTION public.admin_record_payment(p_user_id uuid, p_amount_kzt numeric, p_paid_at timestamptz,
 p_method text, p_comment text DEFAULT '') RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE receipt public.payments;
BEGIN
 IF NOT public.is_subscription_admin() THEN RAISE EXCEPTION 'ADMIN_REQUIRED' USING ERRCODE = '42501'; END IF;
 INSERT INTO public.payments(user_id,amount_kzt,paid_at,method,comment,confirmed_by)
 VALUES(p_user_id,p_amount_kzt,p_paid_at,p_method,p_comment,auth.uid()) RETURNING * INTO receipt;
 INSERT INTO public.admin_audit_logs(actor_id,user_id,action,new_values)
 VALUES(auth.uid(),p_user_id,'payment',to_jsonb(receipt));
 RETURN receipt.id;
END;
$$;
CREATE FUNCTION public.admin_subscription_history(p_user_id uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
 IF NOT public.is_subscription_admin() THEN RAISE EXCEPTION 'ADMIN_REQUIRED' USING ERRCODE = '42501'; END IF;
 RETURN coalesce((SELECT jsonb_agg(to_jsonb(l) ORDER BY created_at DESC, id DESC)
 FROM public.admin_audit_logs l WHERE user_id=p_user_id), '[]'::jsonb);
END;
$$;
-- Audit even owner-issued Dashboard grants/revocations and rollout changes.
CREATE FUNCTION public.audit_subscription_owner_change() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
 INSERT INTO public.admin_audit_logs(actor_id,user_id,action,old_values,new_values)
 VALUES(auth.uid(),CASE WHEN TG_TABLE_NAME='subscription_admins' THEN coalesce(to_jsonb(NEW)->>'user_id',to_jsonb(OLD)->>'user_id')::uuid ELSE NULL END,
 TG_TABLE_NAME||':'||TG_OP,CASE WHEN TG_OP<>'INSERT' THEN to_jsonb(OLD) END,
 CASE WHEN TG_OP<>'DELETE' THEN to_jsonb(NEW) END);
 RETURN NULL;
END;
$$;
CREATE TRIGGER audit_admins AFTER INSERT OR UPDATE OR DELETE ON public.subscription_admins
 FOR EACH ROW EXECUTE FUNCTION public.audit_subscription_owner_change();
CREATE TRIGGER audit_settings AFTER UPDATE ON public.subscription_settings
 FOR EACH ROW EXECUTE FUNCTION public.audit_subscription_owner_change();
-- No public function execution by default (Postgres otherwise grants PUBLIC).
REVOKE ALL ON FUNCTION public.is_subscription_admin(), public.subscription_access(), public.has_subscription_access(),
 public.require_subscription_access(), public.guard_paid_write(), public.admin_subscription_users(),
 public.admin_change_subscription(uuid,text,integer,timestamptz,text,text),
 public.admin_record_payment(uuid,numeric,timestamptz,text,text), public.admin_subscription_history(uuid),
 public.audit_subscription_owner_change() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.is_subscription_admin(), public.subscription_access(), public.has_subscription_access(),
 public.admin_subscription_users(), public.admin_change_subscription(uuid,text,integer,timestamptz,text,text),
 public.admin_record_payment(uuid,numeric,timestamptz,text,text), public.admin_subscription_history(uuid) TO authenticated;

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
BEGIN
    PERFORM public.require_subscription_access();
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

NOTIFY pgrst, 'reload schema';
COMMIT;
