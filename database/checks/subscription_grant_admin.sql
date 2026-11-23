-- OWNER ONLY, Supabase Dashboard SQL Editor. Verify identity in Authentication > Users.
BEGIN;
DO $$
DECLARE
 owner_confirmed boolean := false;
 verified_user_id uuid := NULL; -- replace with verified Auth UUID, never metadata role
BEGIN
 IF NOT owner_confirmed OR verified_user_id IS NULL THEN RAISE EXCEPTION 'OWNER_CONFIRMATION_AND_UUID_REQUIRED'; END IF;
 IF NOT EXISTS(SELECT 1 FROM auth.users WHERE id=verified_user_id) THEN RAISE EXCEPTION 'AUTH_USER_NOT_FOUND'; END IF;
 INSERT INTO public.subscription_admins(user_id) VALUES(verified_user_id) ON CONFLICT DO NOTHING;
END;
$$;
COMMIT;
