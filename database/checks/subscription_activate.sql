-- OWNER ONLY. Does not activate unless explicitly edited after staging tests and grants.
BEGIN;
DO $$
DECLARE owner_confirmed boolean := false;
BEGIN
 IF NOT owner_confirmed THEN RAISE EXCEPTION 'OWNER_CONFIRMATION_REQUIRED'; END IF;
 -- Serialize new signups with activation so a signup cannot miss the readiness check.
 LOCK TABLE auth.users IN SHARE MODE;
 IF NOT EXISTS(SELECT 1 FROM public.subscription_admins) THEN RAISE EXCEPTION 'ADMIN_REQUIRED'; END IF;
 IF EXISTS(SELECT 1 FROM auth.users u LEFT JOIN public.subscriptions s ON s.user_id=u.id
 WHERE s.user_id IS NULL OR s.suspended OR s.starts_at > now() OR s.ends_at <= now()) THEN
 RAISE EXCEPTION 'USERS_WITHOUT_ACCESS_REVIEW_REQUIRED'; END IF;
 UPDATE public.subscription_settings SET enforced=true WHERE id;
END;
$$;
COMMIT;
