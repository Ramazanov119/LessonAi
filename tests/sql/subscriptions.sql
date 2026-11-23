\set ON_ERROR_STOP on
-- Run only against an isolated database after migrations.
INSERT INTO auth.users(id,email,raw_user_meta_data) VALUES
 ('11111111-1111-4111-8111-111111111111','admin@example.test','{"full_name":"Admin"}'),
 ('22222222-2222-4222-8222-222222222222','teacher@example.test','{"full_name":"Teacher"}'),
 ('33333333-3333-4333-8333-333333333333','other@example.test','{"full_name":"Other"}');
INSERT INTO public.subscription_admins(user_id) VALUES('11111111-1111-4111-8111-111111111111');
CREATE FUNCTION pg_temp.assert_true(ok boolean, label text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN IF ok IS DISTINCT FROM true THEN RAISE EXCEPTION 'ASSERTION FAILED: %',label; END IF; END;
$$;
CREATE FUNCTION pg_temp.denied(statement text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 BEGIN EXECUTE statement; EXCEPTION WHEN insufficient_privilege THEN RETURN; END;
 RAISE EXCEPTION 'Expected insufficient_privilege: %', statement;
END;
$$;
SET ROLE authenticated;
SELECT set_config('request.jwt.claim.sub','22222222-2222-4222-8222-222222222222',false);
SELECT pg_temp.assert_true(public.has_subscription_access(),'rollout retains existing access');
SELECT pg_temp.assert_true(NOT public.is_subscription_admin(),'teacher is not admin');
SELECT pg_temp.denied('SELECT public.admin_subscription_users()');
SELECT pg_temp.denied($q$UPDATE public.subscriptions SET ends_at=now()+interval '1 year'$q$);
SELECT pg_temp.denied($q$INSERT INTO public.subscription_admins(user_id) VALUES(auth.uid())$q$);
SELECT pg_temp.denied($q$SELECT public.admin_change_subscription(auth.uid(),'extend',30)$q$);
SELECT pg_temp.denied($q$SELECT public.admin_record_payment(auth.uid(),1000,now(),'cash','')$q$);
-- Legacy editable profile/metadata privileges cannot grant administrative rights.
UPDATE public.profiles SET role='admin' WHERE id=auth.uid();
SELECT pg_temp.assert_true(NOT public.is_subscription_admin(),'legacy profile role does not grant admin');
SELECT set_config('request.jwt.claim.sub','11111111-1111-4111-8111-111111111111',false);
SELECT pg_temp.assert_true(public.is_subscription_admin(),'admin recognized');
SELECT pg_temp.assert_true(jsonb_array_length(public.admin_subscription_users())=3,'admin sees Auth users');
SELECT public.admin_change_subscription('22222222-2222-4222-8222-222222222222','extend',30);
SELECT public.admin_change_subscription('11111111-1111-4111-8111-111111111111','extend',30);
SELECT public.admin_record_payment('22222222-2222-4222-8222-222222222222',2500,now(),'transfer','manual');
RESET ROLE;
UPDATE public.subscription_settings SET enforced=true;
SET ROLE authenticated;
SELECT set_config('request.jwt.claim.sub','33333333-3333-4333-8333-333333333333',false);
SELECT pg_temp.assert_true(NOT public.has_subscription_access(),'missing subscription denied');
SELECT set_config('request.jwt.claim.sub','22222222-2222-4222-8222-222222222222',false);
SELECT pg_temp.assert_true(public.has_subscription_access(),'active teacher allowed');
SELECT * FROM public.save_lesson_plan_with_daily_limit('Math','Topic','Group',1,'70 минут',current_date,'ru','New','IT','Math','{"goal":"test"}', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa');
SELECT pg_temp.assert_true((SELECT count(*)=1 FROM public.lessons),'lesson created');
SELECT pg_temp.assert_true((SELECT count(*)=1 FROM public.lesson_materials),'document created');
SELECT id AS stored_lesson FROM public.lessons LIMIT 1 \gset
SELECT set_config('request.jwt.claim.sub','11111111-1111-4111-8111-111111111111',false);
SELECT pg_temp.assert_true((SELECT count(*)=0 FROM public.lessons),'other session cannot see teacher lessons');
SELECT pg_temp.denied(format('INSERT INTO public.lesson_materials(lesson_id,material_type,content) VALUES(%L,%L,%L)', :'stored_lesson','lecture','foreign lesson'));
SELECT public.admin_change_subscription('22222222-2222-4222-8222-222222222222','suspend',p_reason=>'manual block');
DO $$ BEGIN
 BEGIN
 PERFORM public.admin_change_subscription(auth.uid(),'suspend',p_reason=>'self');
 EXCEPTION WHEN raise_exception THEN
 IF SQLERRM='SELF_SUSPENSION_FORBIDDEN' THEN RETURN; END IF; RAISE;
 END;
 RAISE EXCEPTION 'Self suspension allowed';
END $$;
SELECT set_config('request.jwt.claim.sub','22222222-2222-4222-8222-222222222222',false);
SELECT pg_temp.assert_true(NOT public.has_subscription_access(),'manual suspension overrides future end');
SELECT pg_temp.assert_true((SELECT count(*)=0 FROM public.lesson_materials),'suspended API cannot read materials');
SELECT pg_temp.denied($q$SELECT * FROM public.create_lesson_with_daily_limit('Math','Bypass','Group',1,'70 минут',current_date,'ru','New','IT','Math')$q$);
SELECT pg_temp.denied($q$SELECT * FROM public.save_lesson_plan_with_daily_limit('Math','Topic','Group',1,'70 минут',current_date,'ru','New','IT','Math','{"goal":"test"}', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')$q$);
SELECT pg_temp.denied(format('INSERT INTO public.lesson_materials(lesson_id,material_type,content) VALUES(%L,%L,%L)', :'stored_lesson','lecture','bypass'));
SELECT set_config('request.jwt.claim.sub','11111111-1111-4111-8111-111111111111',false);
SELECT public.admin_change_subscription('22222222-2222-4222-8222-222222222222','resume');
RESET ROLE;
UPDATE public.subscriptions SET starts_at=now()-interval '60 days',ends_at=now()-interval '1 day'
 WHERE user_id='22222222-2222-4222-8222-222222222222';
SET ROLE authenticated;
SELECT set_config('request.jwt.claim.sub','22222222-2222-4222-8222-222222222222',false);
SELECT pg_temp.assert_true(NOT public.has_subscription_access(),'expired access denied');
SELECT pg_temp.denied($q$SELECT * FROM public.create_lesson_with_daily_limit('Math','Topic','Group',1,'70 минут',current_date,'ru','New','IT','Math')$q$);
SELECT set_config('request.jwt.claim.sub','11111111-1111-4111-8111-111111111111',false);
SELECT public.admin_change_subscription('22222222-2222-4222-8222-222222222222','extend',7);
SELECT pg_temp.assert_true(jsonb_array_length(public.admin_subscription_history('22222222-2222-4222-8222-222222222222'))=5,'audited changes and payment');
SELECT set_config('request.jwt.claim.sub','22222222-2222-4222-8222-222222222222',false);
SELECT pg_temp.assert_true(public.has_subscription_access(),'extension restores access');
SELECT pg_temp.assert_true((SELECT count(*)=1 FROM public.lessons),'existing lessons preserved');
SELECT pg_temp.assert_true((SELECT count(*)=1 FROM public.lesson_materials),'existing documents preserved');
RESET ROLE;
SELECT pg_temp.assert_true((SELECT count(*)=1 FROM public.generation_events),'quota unchanged on failed calls');
SELECT pg_temp.assert_true((SELECT count(*)=3 FROM auth.users),'accounts preserved');
-- Exact exclusive boundary, using the same transaction timestamp.
BEGIN;
UPDATE public.subscriptions SET starts_at=now()-interval '2 days', ends_at=now()
 WHERE user_id='22222222-2222-4222-8222-222222222222';
SET ROLE authenticated;
SELECT set_config('request.jwt.claim.sub','22222222-2222-4222-8222-222222222222',true);
SELECT pg_temp.assert_true(NOT public.has_subscription_access(),'exact expiration boundary denied');
ROLLBACK;
BEGIN;
UPDATE public.subscriptions SET starts_at=now()+interval '1 day', ends_at=now()+interval '2 days'
 WHERE user_id='22222222-2222-4222-8222-222222222222';
SET ROLE authenticated;
SELECT set_config('request.jwt.claim.sub','22222222-2222-4222-8222-222222222222',true);
SELECT pg_temp.assert_true(NOT public.has_subscription_access(),'future start denied');
ROLLBACK;
SELECT 'SUBSCRIPTION SQL TESTS PASSED';
