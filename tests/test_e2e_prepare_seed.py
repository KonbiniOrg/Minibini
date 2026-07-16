"""Tests for e2e/seed/prepare_seed.py — the E2E seed rebase script.

The script is pure stdlib (no Django imports) so it can run before any
Django environment exists; these tests import it by file path.
"""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from django.contrib.auth.hashers import check_password

MODULE_PATH = Path(__file__).resolve().parent.parent / 'e2e' / 'seed' / 'prepare_seed.py'

spec = importlib.util.spec_from_file_location('prepare_seed', MODULE_PATH)
prepare_seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_seed)


def record(model, fields, pk=1):
    return {'model': model, 'pk': pk, 'fields': fields}


class ShiftStringTests(unittest.TestCase):
    def test_shifts_full_datetime_preserving_time_and_suffix(self):
        self.assertEqual(
            prepare_seed.shift_string('2026-06-12T13:36:00Z', 3),
            '2026-06-15T13:36:00Z')

    def test_shifts_datetime_with_microseconds(self):
        self.assertEqual(
            prepare_seed.shift_string('2026-04-03T03:37:49.729Z', 10),
            '2026-04-13T03:37:49.729Z')

    def test_shifts_datetime_with_utc_offset(self):
        self.assertEqual(
            prepare_seed.shift_string('2026-06-12T13:36:00+00:00', 1),
            '2026-06-13T13:36:00+00:00')

    def test_shifts_bare_date(self):
        self.assertEqual(prepare_seed.shift_string('2026-06-12', 2), '2026-06-14')

    def test_shifts_across_month_boundary(self):
        self.assertEqual(prepare_seed.shift_string('2026-06-30', 2), '2026-07-02')

    def test_negative_delta_shifts_backward(self):
        self.assertEqual(prepare_seed.shift_string('2026-06-12', -12), '2026-05-31')

    def test_leaves_document_numbers_alone(self):
        self.assertEqual(prepare_seed.shift_string('JOB-2025-0001', 5), 'JOB-2025-0001')

    def test_leaves_embedded_dates_in_prose_alone(self):
        s = 'Customer called on 2026-06-12 about the order'
        self.assertEqual(prepare_seed.shift_string(s, 5), s)

    def test_leaves_decimals_alone(self):
        self.assertEqual(prepare_seed.shift_string('123.45', 5), '123.45')


class ComputeDeltaDaysTests(unittest.TestCase):
    def test_lands_newest_job_history_timestamp_on_yesterday(self):
        records = [record('core.jobhistory', {'timestamp': '2026-06-12T13:36:00Z'})]
        self.assertEqual(
            prepare_seed.compute_delta_days(records, today=date(2026, 7, 15)), 32)

    def test_anchor_ignores_every_other_model(self):
        # Job history can never postdate "now"; deadline fields (estimate
        # expirations, due dates) and session expiry legitimately sit in the
        # dataset's future and must not be mistaken for the present.
        records = [
            record('core.jobhistory', {'timestamp': '2026-06-12T13:36:00Z'}),
            record('jobs.blep', {'end_time': '2026-06-20T09:00:00Z'}),
            record('estimates.estimate', {'expiration_date': '2026-08-09T00:00:00Z'}),
            record('jobs.job', {'due_date': '2026-09-01'}),
            record('sessions.session', {'expire_date': '2026-07-29T03:37:49.729Z'}, pk='abc'),
        ]
        self.assertEqual(
            prepare_seed.compute_delta_days(records, today=date(2026, 7, 15)), 32)

    def test_raises_when_no_job_history_present(self):
        records = [record('jobs.blep', {'end_time': '2026-06-12T13:36:00Z'})]
        with self.assertRaises(ValueError):
            prepare_seed.compute_delta_days(records, today=date(2026, 7, 15))

    def test_zero_delta_when_anchor_already_yesterday(self):
        records = [record('core.jobhistory', {'timestamp': '2026-07-14T09:00:00Z'})]
        self.assertEqual(
            prepare_seed.compute_delta_days(records, today=date(2026, 7, 15)), 0)


class RebaseTests(unittest.TestCase):
    def test_shifts_all_values_by_one_constant_delta(self):
        records = [
            record('core.jobhistory', {'timestamp': '2026-06-12T13:36:00Z'}),
            record('estimates.estimate', {'expiration_date': '2026-08-09T00:00:00Z'}),
        ]
        rebased, delta = prepare_seed.rebase(records, today=date(2026, 7, 15))
        self.assertEqual(delta, 32)
        self.assertEqual(rebased[0]['fields']['timestamp'], '2026-07-14T13:36:00Z')
        # Deadlines shift by the same delta: relative gaps are preserved.
        self.assertEqual(rebased[1]['fields']['expiration_date'], '2026-09-10T00:00:00Z')

    def test_shifts_dates_nested_in_lists_and_dicts(self):
        records = [
            record('core.jobhistory', {'timestamp': '2026-06-12T13:36:00Z'}),
            record('core.tempemail', {'attachments_metadata': [
                {'filename': 'a.pdf', 'received': '2026-06-01T10:00:00Z'}]}),
        ]
        rebased, _ = prepare_seed.rebase(records, today=date(2026, 7, 15))
        self.assertEqual(
            rebased[1]['fields']['attachments_metadata'][0]['received'],
            '2026-07-03T10:00:00Z')

    def test_overwrites_user_passwords_with_known_hash(self):
        records = [
            record('core.user', {'username': 'schen', 'password': 'pbkdf2_sha256$whatever'}),
            record('core.jobhistory', {'timestamp': '2026-06-12T13:36:00Z'}),
        ]
        rebased, _ = prepare_seed.rebase(records, today=date(2026, 7, 15))
        self.assertEqual(rebased[0]['fields']['password'],
                         prepare_seed.E2E_PASSWORD_HASH)

    def test_baked_hash_actually_verifies_e2e_password(self):
        self.assertTrue(check_password('e2e_password', prepare_seed.E2E_PASSWORD_HASH))

    def test_leaves_non_date_fields_untouched(self):
        records = [
            record('core.jobhistory', {'timestamp': '2026-06-12T13:36:00Z'}),
            record('jobs.job', {
                'job_number': 'JOB-2025-0001',
                'description': 'Due 2026-06-20 per customer',
                'created_at': '2026-06-01T08:00:00Z',
            }),
        ]
        rebased, _ = prepare_seed.rebase(records, today=date(2026, 7, 15))
        self.assertEqual(rebased[1]['fields']['job_number'], 'JOB-2025-0001')
        self.assertEqual(rebased[1]['fields']['description'],
                         'Due 2026-06-20 per customer')

    def test_rebasing_already_rebased_data_is_a_noop(self):
        records = [record('core.jobhistory', {'timestamp': '2026-06-12T13:36:00Z'})]
        once, _ = prepare_seed.rebase(records, today=date(2026, 7, 15))
        twice, delta = prepare_seed.rebase(once, today=date(2026, 7, 15))
        self.assertEqual(delta, 0)
        self.assertEqual(once, twice)


class MainTests(unittest.TestCase):
    def test_writes_rebased_copy_and_leaves_source_untouched(self):
        records = [record('core.jobhistory', {'timestamp': '2026-06-12T13:36:00Z'})]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'seed.json'
            out = Path(tmp) / 'rebased.json'
            original = json.dumps(records)
            src.write_text(original)
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                prepare_seed.main(path=src, out_path=out, today=date(2026, 7, 15))
            self.assertIn('+32 days', stdout.getvalue())
            self.assertEqual(src.read_text(), original)  # source is frozen
            text = out.read_text()
            self.assertTrue(text.startswith('[\n{\n'))
            self.assertEqual(
                json.loads(text)[0]['fields']['timestamp'],
                '2026-07-14T13:36:00Z')


if __name__ == '__main__':
    unittest.main()
