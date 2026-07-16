"""Tests for the DATABASE_NAME guard in e2e/seed/reset_db.sh.

Only the guard is unit-tested — it's the belt-and-braces that keeps the
script off the dev database, and it must fail *before* any mysql/Django
command runs. The happy path (drop, create, migrate, seed) is exercised
by every real Playwright run via global-setup.js.
"""
import os
import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / 'e2e' / 'seed' / 'reset_db.sh'


class ResetDbGuardTests(unittest.TestCase):
    def run_script(self, database_name=None):
        env = {k: v for k, v in os.environ.items() if k != 'DATABASE_NAME'}
        if database_name is not None:
            env['DATABASE_NAME'] = database_name
        return subprocess.run(['bash', str(SCRIPT)], env=env,
                              capture_output=True, text=True, timeout=10)

    def test_refuses_when_database_name_unset(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn('DATABASE_NAME must be minibini_e2e',
                      result.stderr + result.stdout)

    def test_refuses_when_database_name_is_the_dev_db(self):
        result = self.run_script('minibini_db')
        self.assertEqual(result.returncode, 1)
        self.assertIn('DATABASE_NAME must be minibini_e2e',
                      result.stderr + result.stdout)


if __name__ == '__main__':
    unittest.main()
