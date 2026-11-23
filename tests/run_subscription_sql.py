"""Run isolated SQL integration tests: python tests/run_subscription_sql.py.
Requires Docker and postgres:17-bookworm. No network ports or production credentials.
"""
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    'tests/sql/subscription_setup.sql',
    'database/migrations/001_profiles_lessons_quota.sql',
    'database/migrations/002_unique_topic_fixed_duration.sql',
    'database/migrations/003_lesson_materials.sql',
    'database/migrations/004_add_alt_college.sql',
    'database/migrations/005_add_atkk_college.sql',
    'database/migrations/004_atomic_lesson_plan.sql',
    'database/migrations/006_subscriptions.sql',
    'tests/sql/subscriptions.sql',
]


def main():
    import time
    container = 'lessonai-subscriptions-' + uuid.uuid4().hex[:12]
    subprocess.run(['docker', 'run', '--rm', '-d', '--name', container, '--network', 'none',
                    '-e', 'POSTGRES_PASSWORD=local-test-only', 'postgres:17-bookworm'], check=True)
    try:
        for _ in range(60):
            if subprocess.run(['docker', 'exec', container, 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError('Test PostgreSQL did not become ready')
        source = '\\set ON_ERROR_STOP on\n' + '\n'.join((ROOT / f).read_text() for f in FILES)
        subprocess.run(['docker', 'exec', '-i', '-e', 'PGPASSWORD=local-test-only', container, 'psql', '-h', '127.0.0.1', '-U', 'postgres'],
                       input=source, text=True, check=True)
    finally:
        subprocess.run(['docker', 'rm', '-f', container], check=True, stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
