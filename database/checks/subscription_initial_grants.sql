-- OWNER ONLY. Separate from migration. Preview first; edit both dates and confirmation.
-- Creates subscriptions only for existing Auth users; does not overwrite existing grants.
BEGIN;
DO $$
DECLARE
 owner_confirmed boolean := false; -- set true ONLY after owner approves dates and preview
 cohort_cutoff timestamptz := NULL; -- exact reviewed signup cutoff
 initial_end timestamptz := NULL; -- exact approved end date with timezone
BEGIN
 IF NOT owner_confirmed OR cohort_cutoff IS NULL OR initial_end IS NULL OR initial_end <= now() THEN
   RAISE EXCEPTION 'OWNER_CONFIRMATION_AND_DATES_REQUIRED';
 END IF;
 WITH granted AS (
 INSERT INTO public.subscriptions(user_id,plan,ends_at,reason)
 SELECT id,'standard',initial_end,'Первоначальная выдача, подтверждено владельцем'
 FROM auth.users WHERE created_at <= cohort_cutoff
 ON CONFLICT(user_id) DO NOTHING RETURNING *
 )
 INSERT INTO public.admin_audit_logs(actor_id,user_id,action,new_values)
 SELECT auth.uid(),user_id,'owner_initial_grant',to_jsonb(granted) FROM granted;
END;
$$;
COMMIT;
