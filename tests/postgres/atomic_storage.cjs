// Always starts its own disposable loopback cluster; never accepts a database URL.
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const assert = require('node:assert/strict');
const {randomUUID} = require('node:crypto');
const {pathToFileURL} = require('node:url');
const {execFileSync} = require('node:child_process');

async function main() {
  const tools = process.env.LESSONAI_PG_TOOLS || '/private/tmp/lessonai-pg-tools/node_modules';
  const {default: EmbeddedPostgres} = await import(pathToFileURL(path.join(tools, 'embedded-postgres/dist/index.js')));
  const {Client} = require(path.join(tools, 'pg'));
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'lessonai-isolated-pg-'));
  const listener = net.createServer();
  await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
  const port = listener.address().port;
  await new Promise(resolve => listener.close(resolve));
  const password = randomUUID();
  const pg = new EmbeddedPostgres({databaseDir: path.join(temp, 'data'), port, user: 'postgres', password,
    persistent: false, createPostgresUser: false, postgresFlags: ['-h', '127.0.0.1', '-k', temp],
    onLog: () => {}, onError: () => {}});
  const connections = [];
  const root = path.resolve(__dirname, '../..');
  const migration = await fs.readFile(path.join(root, 'database/migrations/004_atomic_lesson_plan.sql'), 'utf8');
  const legacyDefinition = `CREATE FUNCTION public.save_lesson_plan_with_daily_limit(
    p_subject text,p_topic text,p_group_name text,p_course integer,p_duration text,p_lesson_date date,
    p_language text,p_lesson_type text,p_speciality text,p_chair text,p_material_content text,p_existing_lesson_id uuid DEFAULT NULL
  ) RETURNS TABLE(lesson_id uuid,daily_count integer) LANGUAGE sql SECURITY DEFINER AS $$ SELECT NULL::uuid,0 $$;`;
  let admin, passed = 0;
  const users = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'];
  async function connect(role, user = users[0]) {
    const client = new Client({host: '127.0.0.1', port, user: 'postgres', password, database: 'postgres'});
    await client.connect(); connections.push(client);
    if (role) await client.query(`SET ROLE ${role}`); // Fixed test roles only.
    if (user) await client.query("SELECT set_config('request.jwt.claim.sub', $1, false)", [user]);
    return client;
  }
  async function counts() {
    return (await admin.query('SELECT (SELECT count(*)::int FROM lessons) AS lessons, (SELECT count(*)::int FROM generation_events) AS events, (SELECT count(*)::int FROM lesson_materials) AS materials, (SELECT count(*)::int FROM lesson_plan_operations) AS operations')).rows[0];
  }
  const callSql = 'SELECT * FROM public.save_lesson_plan_with_daily_limit($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)';
  function args({topic = 'iOS', content = '{"goal":"Synthetic lesson"}', op = randomUUID(), existing = null} = {}) {
    return ['Mobile development', topic, 'TEST', 1, '70 минут', '2026-10-13', 'Русский', 'Новый урок', 'IT', 'Test chair', content, op, existing];
  }
  async function expectCode(promise, code, token) {
    await assert.rejects(promise, e => e.code === code && (!token || e.message.includes(token)));
  }
  async function test(name, run) {
    await admin.query('TRUNCATE public.lessons CASCADE');
    await admin.query("UPDATE profiles SET college = 'META'");
    await run(); passed++; console.log('PASS ' + name);
  }
  try {
    await pg.initialise(); await pg.start(); admin = await connect();
    console.log((await admin.query('SELECT version()')).rows[0].version.split(' on ')[0]);
    await admin.query(`CREATE ROLE anon; CREATE ROLE authenticated;
      CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY, email text, raw_user_meta_data jsonb DEFAULT '{}');
      CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
      GRANT USAGE ON SCHEMA auth TO authenticated, anon; GRANT EXECUTE ON FUNCTION auth.uid() TO authenticated, anon;`);
    const baseline = await fs.readFile(path.join(root, 'database/migrations/001_profiles_lessons_quota.sql'), 'utf8');
    await admin.query(baseline);
    for (const file of ['002_unique_topic_fixed_duration.sql', '003_lesson_materials.sql', '004_add_alt_college.sql', '005_add_atkk_college.sql'])
      await admin.query(await fs.readFile(path.join(root, 'database/migrations', file), 'utf8'));
    await admin.query('INSERT INTO auth.users(id,email,raw_user_meta_data) VALUES ($1,$2,$3),($4,$5,$3)',
      [users[0], 'test-one@example.invalid', JSON.stringify({full_name: 'Synthetic teacher', college: 'META'}), users[1], 'test-two@example.invalid']);
    await admin.query(legacyDefinition);
    await admin.query('GRANT EXECUTE ON FUNCTION public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid) TO authenticated');
    for (const file of ['lesson_plan_preupgrade.sql', 'lesson_plan_backup.sql'])
      await admin.query(await fs.readFile(path.join(root, 'database/checks', file), 'utf8'));
    await admin.query(migration); await admin.query(migration);
    await admin.query(await fs.readFile(path.join(root, 'database/checks/lesson_plan_postupgrade.sql'), 'utf8'));
    const teacher = await connect('authenticated');
    const other = await connect('authenticated', users[1]);
    const anon = await connect('anon', null);
    const status = async () => (await teacher.query('SELECT public.lesson_plan_storage_status() AS status')).rows[0].status;
    await test('repeatable migration and read-only readiness', async () => {
      await admin.query(await fs.readFile(path.join(root, 'database/checks/lesson_plan_storage.sql'), 'utf8'));
      assert.deepEqual(await status(), {ready: true, reasons: [], api_version: 2});
      assert.deepEqual(await counts(), {lessons: 0, events: 0, materials: 0, operations: 0});
      assert.equal((await admin.query("SELECT to_regprocedure('public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid)') AS legacy")).rows[0].legacy, null);
    });
    await test('existing target replacement preserves identity owner and custom ACL', async () => {
      await admin.query('CREATE ROLE lessonai_saved_caller');
      const identity = "to_regprocedure('public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid)')";
      const before = (await admin.query(`SELECT oid, proowner FROM pg_proc WHERE oid=${identity}`)).rows[0];
      await admin.query('GRANT EXECUTE ON FUNCTION public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid) TO lessonai_saved_caller WITH GRANT OPTION');
      await admin.query(migration);
      assert.deepEqual((await admin.query(`SELECT oid, proowner FROM pg_proc WHERE oid=${identity}`)).rows[0], before);
      const acl = (await admin.query(`SELECT a.is_grantable FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a WHERE p.oid=${identity} AND a.grantee='lessonai_saved_caller'::regrole`)).rows[0];
      assert.equal(acl.is_grantable, true);
      await admin.query('REVOKE EXECUTE ON FUNCTION public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid) FROM lessonai_saved_caller');
      await admin.query('DROP ROLE lessonai_saved_caller');
    });
    await test('unknown overload blocks migration before changing the schema', async () => {
      await admin.query('CREATE FUNCTION public.save_lesson_plan_with_daily_limit(integer) RETURNS integer LANGUAGE sql AS $$ SELECT $1 $$');
      await expectCode(admin.query(migration), 'P0001', 'UNREVIEWED_SAVE_RPC_OVERLOAD');
      await admin.query('ROLLBACK');
      assert.equal((await status()).ready, true);
      await admin.query('DROP FUNCTION public.save_lesson_plan_with_daily_limit(integer)');
    });
    await test('same types but reversed UUID argument names require review', async () => {
      await admin.query('DROP FUNCTION public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid)');
      const wrong = legacyDefinition.replace('p_existing_lesson_id uuid DEFAULT NULL', 'p_existing_lesson_id uuid,p_operation_id uuid DEFAULT NULL');
      await admin.query(wrong);
      await expectCode(admin.query(migration), 'P0001', 'TARGET_SAVE_RPC_ARGUMENT_REVIEW_REQUIRED');
      await admin.query('ROLLBACK');
      await admin.query('DROP FUNCTION public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid)');
      await admin.query(migration);
    });
    await test('legacy dependency aborts migration without cascading deletion', async () => {
      await admin.query(legacyDefinition);
      await admin.query("CREATE VIEW public.lessonai_legacy_dependency AS SELECT * FROM public.save_lesson_plan_with_daily_limit('S','T','G',1,'70','2026-10-13'::date,'ru','new','IT','C','{}',NULL::uuid)");
      await expectCode(admin.query(migration), '2BP01');
      await admin.query('ROLLBACK');
      assert.ok((await admin.query("SELECT to_regclass('public.lessonai_legacy_dependency') AS view")).rows[0].view);
      await admin.query('DROP VIEW public.lessonai_legacy_dependency');
      await admin.query(migration);
    });
    await test('regression: legacy SQL output-variable ambiguity is fixed', async () => {
      await admin.query(migration.replace('#variable_conflict use_column\n', ''));
      await expectCode(teacher.query(callSql, args()), '42702');
      assert.equal((await counts()).events, 0);
      await admin.query(migration);
      await teacher.query(callSql, args());
      assert.equal((await counts()).events, 1);
    });
    await test('readiness detects college constraints incompatible with Q', async () => {
      await admin.query("ALTER TABLE profiles DROP CONSTRAINT profiles_college_check; ALTER TABLE profiles ADD CONSTRAINT profiles_college_check CHECK(college IN ('META','ETEC','ALT','ATKK'))");
      assert.ok((await status()).reasons.includes('college_constraints'));
      await admin.query("ALTER TABLE profiles DROP CONSTRAINT profiles_college_check; ALTER TABLE profiles ADD CONSTRAINT profiles_college_check CHECK(college IN ('META','ETEC','ALT','ATKK','Q'))");
    });
    await test('readiness detects missing signature', async () => {
      await admin.query('ALTER FUNCTION public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid) RENAME TO temporarily_missing');
      assert.equal((await status()).ready, false);
      await admin.query('ALTER FUNCTION public.temporarily_missing(text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid) RENAME TO save_lesson_plan_with_daily_limit');
    });
    await test('readiness detects execution permission', async () => {
      await admin.query('REVOKE EXECUTE ON FUNCTION public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid) FROM authenticated');
      assert.ok((await status()).reasons.includes('save_rpc_permission'));
      await admin.query('GRANT EXECUTE ON FUNCTION public.save_lesson_plan_with_daily_limit(text,text,text,integer,text,date,text,text,text,text,text,uuid,uuid) TO authenticated');
    });
    await test('all five college constraints accept atomic saves', async () => {
      for (const college of ['META', 'Q', 'ETEC', 'ALT', 'ATKK']) {
        await admin.query('UPDATE profiles SET college=$1 WHERE id=$2', [college, users[0]]);
        await teacher.query(callSql, args({topic: college + ' topic'}));
      }
      assert.deepEqual(await counts(), {lessons: 5, events: 5, materials: 5, operations: 5});
    });
    await test('saved META and Q JSON through Python normalization and DOCX to real SQL', async () => {
      for (const college of ['META', 'Q']) {
        const python = `import json,sys
from pathlib import Path
from dataclasses import replace
sys.path.insert(0, 'tests')
from test_meta_task_links import metadata
from services.lesson_plan_service import prepare_lesson_plan
from config.colleges import get_college_config
from docx import Document
college=sys.argv[1]
source=Path('tests/fixtures/meta_ios_95_ru.json' if college=='META' else 'docs/qa/q/lesson_q_ru.json')
md=replace(metadata(college), topic='Операционная система iOS' if college=='META' else 'Проверка связей')
doc,content=prepare_lesson_plan(json.loads(source.read_text()),md,get_college_config(college)['template'],operation_id=sys.argv[2])
word=Document(doc)
if college=='META': assert len(word.tables[2].columns)==5 and sum(int(r.cells[4].text) for r in word.tables[2].rows[1:-1])==100
print(json.dumps({'content':content,'subject':md.subject,'topic':md.topic,'group':md.group_name,'date':md.lesson_date.isoformat()},ensure_ascii=False))`;
        const op = randomUUID();
        const prepared = JSON.parse(execFileSync(path.join(root, '.venv/bin/python'), ['-c', python, college, op], {cwd: root, encoding: 'utf8', env: {...process.env, PYTHONPYCACHEPREFIX: path.join(temp, 'pycache')}}));
        await admin.query('UPDATE profiles SET college=$1 WHERE id=$2', [college, users[0]]);
        const request = args({topic: prepared.topic, content: prepared.content, op});
        request[0] = prepared.subject; request[2] = prepared.group; request[5] = prepared.date;
        const id = (await teacher.query(callSql, request)).rows[0].lesson_id;
        const saved = (await admin.query('SELECT content FROM lesson_materials WHERE lesson_id=$1', [id])).rows[0].content;
        assert.equal(saved, prepared.content);
        const lesson = JSON.parse(saved);
        if (college === 'META') {
          assert.equal(lesson.assessment_items.reduce((sum, item) => sum + item.points, 0), 100);
          assert.equal(lesson.lesson_stages.reduce((sum, stage) => sum + stage.duration_minutes, 0), 70);
        } else assert.ok(lesson.interdisciplinary_connections);
      }
      assert.equal((await counts()).events, 2);
    });
    await test('lost response retry is idempotent', async () => {
      const request = args();
      const first = (await teacher.query(callSql, request)).rows;
      assert.deepEqual((await teacher.query(callSql, request)).rows, first);
      assert.deepEqual(await counts(), {lessons: 1, events: 1, materials: 1, operations: 1});
    });
    await test('changed payload with same key is rejected', async () => {
      const request = args(); await teacher.query(callSql, request);
      request[10] = '{"goal":"Changed"}';
      await expectCode(teacher.query(callSql, request), 'P0001', 'IDEMPOTENCY_CONFLICT');
      assert.equal((await counts()).events, 1);
    });
    await test('foreign lesson cannot be updated', async () => {
      const id = (await teacher.query(callSql, args())).rows[0].lesson_id;
      await expectCode(other.query(callSql, args({existing: id})), 'P0001', 'LESSON_NOT_FOUND');
      assert.equal((await counts()).events, 1);
    });
    await test('material failure rolls back lesson and quota', async () => {
      await admin.query("ALTER TABLE lesson_materials ADD CONSTRAINT test_reject CHECK(content NOT LIKE '%reject-me%')");
      await expectCode(teacher.query(callSql, args({content: '{"goal":"reject-me"}'})), '23514');
      assert.deepEqual(await counts(), {lessons: 0, events: 0, materials: 0, operations: 0});
      await admin.query('ALTER TABLE lesson_materials DROP CONSTRAINT test_reject');
    });
    await test('concurrent same operation charges once', async () => {
      const parallel = await connect('authenticated'); const request = args();
      const results = await Promise.all([teacher.query(callSql, request), parallel.query(callSql, request)]);
      assert.deepEqual(results[0].rows, results[1].rows);
      assert.equal((await counts()).events, 1);
    });
    await test('parallel requests respect the unchanged eight lesson limit', async () => {
      for (let i = 0; i < 7; i++) await teacher.query(callSql, args({topic: 'Seed ' + i}));
      const parallel = await connect('authenticated');
      const results = await Promise.allSettled([teacher.query(callSql, args({topic: 'Parallel A'})), parallel.query(callSql, args({topic: 'Parallel B'}))]);
      assert.equal(results.filter(r => r.status === 'fulfilled').length, 1);
      assert.ok(results.find(r => r.status === 'rejected').reason.message.includes('DAILY_LIMIT_REACHED'));
      assert.equal((await counts()).events, 8);
    });
    await test('anonymous role and direct operation table access are denied', async () => {
      await expectCode(anon.query(callSql, args()), '42501');
      await expectCode(anon.query('SELECT lesson_plan_storage_status()'), '42501');
      await expectCode(teacher.query('SELECT * FROM lesson_plan_operations'), '42501');
    });
    await test('deleted lesson is never resurrected by a retry', async () => {
      const request = args(); const id = (await teacher.query(callSql, request)).rows[0].lesson_id;
      await admin.query('DELETE FROM lessons WHERE id=$1', [id]);
      await expectCode(teacher.query(callSql, request), 'P0001', 'LESSON_NOT_FOUND');
      assert.equal((await counts()).lessons, 0);
    });
    await test('invalid JSON and missing operation key never charge', async () => {
      await expectCode(teacher.query(callSql, args({content: 'not-json'})), '22P02');
      await expectCode(teacher.query(callSql, args({op: null})), 'P0001', 'OPERATION_ID_REQUIRED');
      assert.equal((await counts()).events, 0);
    });
    await test('existing owned lesson update does not charge again', async () => {
      const id = (await teacher.query(callSql, args())).rows[0].lesson_id;
      await teacher.query(callSql, args({existing: id, content: '{"goal":"Updated"}'}));
      assert.deepEqual(await counts(), {lessons: 1, events: 1, materials: 1, operations: 2});
    });
    console.log('PostgreSQL integration checks passed: ' + passed);
  } finally {
    for (const client of connections) await client.end().catch(() => {});
    await pg.stop().catch(() => {});
    await fs.rm(temp, {recursive: true, force: true});
  }
}
main().catch(error => {console.error(error.code || error.name, error.message); process.exitCode = 1;});
