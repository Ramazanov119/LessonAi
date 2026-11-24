"""Execute the migration on a disposable Unix-socket PostgreSQL, never Supabase."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from services.supabase_service import SupabaseService
from test_meta_task_links import metadata

ROOT = Path(__file__).resolve().parents[1]
OPERATION = '33333333-3333-4333-8333-333333333333'


@unittest.skipUnless(all(shutil.which(name) for name in ('initdb', 'pg_ctl', 'psql')),
                     'Requires local PostgreSQL binaries')
class ProfileLimitSqlTests(unittest.TestCase):
    def test_migration_permissions_named_python_arguments_and_last_generation(self):
        with tempfile.TemporaryDirectory(prefix='lai-pg-', dir='/private/tmp') as directory:
            data = str(Path(directory) / 'data')
            def command(args, **kwargs):
                result = subprocess.run(args, capture_output=True, text=True, **kwargs)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            command(['initdb', '-D', data, '-U', 'postgres', '-A', 'trust', '--no-locale', '-E', 'UTF8'])
            command(['pg_ctl', '-D', data, '-l', str(Path(directory) / 'postgres.log'),
                     '-o', f"-F -k {directory} -c listen_addresses=''", '-w', 'start'])
            try:
                def sql(source):
                    return command(['psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1', '-h', directory,
                                    '-U', 'postgres', '-d', 'postgres'], input=source)
                files = [
                    'tests/sql/subscription_setup.sql',
                    'database/migrations/001_profiles_lessons_quota.sql',
                    'database/migrations/002_unique_topic_fixed_duration.sql',
                    'database/migrations/003_lesson_materials.sql',
                    'database/migrations/004_add_alt_college.sql',
                    'database/migrations/005_add_atkk_college.sql',
                    'database/migrations/004_atomic_lesson_plan.sql',
                    'database/migrations/006_subscriptions.sql',
                ]
                sql('\n'.join((ROOT / name).read_text() for name in files))
                sql('''
ALTER TABLE public.profiles ADD COLUMN daily_limit_v1 integer;
CREATE TABLE public.generation_logs (
 user_id uuid, status text, created_at timestamptz DEFAULT now()
);
INSERT INTO auth.users(id, email, raw_user_meta_data) VALUES
 ('11111111-1111-4111-8111-111111111111', 'test@example.invalid',
  '{"full_name":"Test teacher", "college":"Q"}');
UPDATE public.profiles SET daily_limit_v1=12;
INSERT INTO public.generation_logs(user_id,status)
 SELECT '11111111-1111-4111-8111-111111111111', 'success' FROM generate_series(1,12);
REVOKE EXECUTE ON FUNCTION public.create_lesson_with_daily_limit(
 text,text,text,integer,text,date,text,text,text,text) FROM authenticated;
DROP FUNCTION public.save_lesson_plan_with_daily_limit(
 text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid);
''')
                migration = (ROOT / 'database/migrations/007_profile_generation_limit.sql').read_text()
                sql(migration)
                sql(migration)  # Re-running the updated SQL restores the same contract.
                connection = Mock()
                connection.rpc.return_value.execute.return_value.data = [{'lesson_id': 'test', 'daily_count': 12}]
                SupabaseService(connection).save_lesson_plan(metadata('Q'), '{"goal":"Test"}', operation_id=OPERATION)
                rpc, parameters = connection.rpc.call_args.args
                def literal(value):
                    if value is None:
                        return 'NULL'
                    if isinstance(value, int):
                        return str(value)
                    return "'" + str(value).replace("'", "''") + "'"
                call = 'SELECT * FROM public.' + rpc + '(' + ','.join(
                    key + ' => ' + literal(value) for key, value in parameters.items()) + ');'
                output = sql('''
SET ROLE authenticated;
SELECT set_config('request.jwt.claim.sub','11111111-1111-4111-8111-111111111111',false);
''' + call + call + '''
RESET ROLE;
DO $$ BEGIN
 IF (SELECT count(*) FROM public.lessons) <> 1
 OR (SELECT count(*) FROM public.lesson_materials) <> 1
 OR (SELECT count(*) FROM public.generation_logs) <> 12 THEN
  RAISE EXCEPTION 'Atomic/idempotent save at personal limit failed';
 END IF;
 IF NOT has_function_privilege('authenticated',
  'public.create_lesson_with_daily_limit(text,text,text,integer,text,date,text,text,text,text)',
  'EXECUTE') OR NOT has_function_privilege('authenticated',
  'public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid)',
  'EXECUTE') THEN RAISE EXCEPTION 'Authenticated RPC grants missing'; END IF;
 IF has_function_privilege('anon',
  'public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid)',
  'EXECUTE') OR has_function_privilege('anon',
  'public.create_lesson_with_daily_limit(text,text,text,integer,text,date,text,text,text,text)',
  'EXECUTE') THEN RAISE EXCEPTION 'Anonymous RPC must be denied'; END IF;
END $$;
''')
                self.assertIn('12', output)
            finally:
                command(['pg_ctl', '-D', data, '-m', 'immediate', '-w', 'stop'])
