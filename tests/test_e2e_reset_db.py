"""Tests for the DATABASE_NAME guard (e2e/seed/db_guard.sh) in reset_db.sh and ensure_db.sh.

Only the guard is unit-tested — it's the belt-and-braces that keeps the
script off the dev database, and it must fail *before* any mysql/Django
command runs. The happy path (drop, create, migrate, seed) is exercised
by every real Playwright run via global-setup.js.
"""
import os
import subprocess
import unittest
from pathlib import Path

SEED = Path(__file__).resolve().parent.parent / 'e2e' / 'seed'


class ResetDbGuardTests(unittest.TestCase):
    script = SEED / 'reset_db.sh'

    def run_script(self, database_name=None):
        env = {k: v for k, v in os.environ.items() if k != 'DATABASE_NAME'}
        if database_name is not None:
            env['DATABASE_NAME'] = database_name
        return subprocess.run(['bash', str(self.script)], env=env,
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

    def test_refuses_slot_lookalikes(self):
        # Per-checkout DBs are minibini_e2e_s1..s9 (e2e/lib/slot.js). The
        # name is interpolated into DROP DATABASE, so the guard is the only
        # thing keeping anything else (or injected SQL) out of it.
        for name in ('minibini_e2e_s0', 'minibini_e2e_s12', 'minibini_e2e_x',
                     'minibini_e2e_s1; DROP DATABASE minibini_db'):
            with self.subTest(name=name):
                result = self.run_script(name)
                self.assertEqual(result.returncode, 1)
                self.assertIn('DATABASE_NAME must be minibini_e2e',
                              result.stderr + result.stdout)


class EnsureDbGuardTests(ResetDbGuardTests):
    script = SEED / 'ensure_db.sh'


if __name__ == '__main__':
    unittest.main()
