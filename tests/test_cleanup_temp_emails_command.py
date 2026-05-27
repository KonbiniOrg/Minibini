from datetime import timedelta
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from apps.core.models import Configuration, EmailRecord, TempEmail, ScheduledProcessRun


class CleanupTempEmailsCommandTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='email_retention_days', value='90')

    def _make_temp(self, message_id, age_days):
        rec = EmailRecord.objects.create(message_id=message_id)
        temp = TempEmail.objects.create(
            email_record=rec, uid='u-' + message_id, subject='s',
            from_email='a@b.com', to_email='c@d.com',
            date_sent=timezone.now(),
        )
        # created_at is auto_now_add; backdate via update() to bypass it.
        TempEmail.objects.filter(pk=temp.pk).update(
            created_at=timezone.now() - timedelta(days=age_days)
        )
        return rec, temp

    def test_deletes_old_keeps_recent_preserves_record(self):
        old_rec, _ = self._make_temp('old', 120)
        new_rec, _ = self._make_temp('new', 10)

        call_command('cleanup_temp_emails')

        self.assertFalse(TempEmail.objects.filter(email_record=old_rec).exists())
        self.assertTrue(TempEmail.objects.filter(email_record=new_rec).exists())
        # Permanent records survive regardless.
        self.assertTrue(EmailRecord.objects.filter(pk=old_rec.pk).exists())

    def test_writes_run_record(self):
        self._make_temp('old', 120)
        call_command('cleanup_temp_emails')
        run = ScheduledProcessRun.objects.get(process_name='cleanup_temp_emails')
        self.assertEqual(run.outcome, 'ok')
        self.assertEqual(run.summary, {'deleted': 1})
