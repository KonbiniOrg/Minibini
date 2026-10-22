from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient
from apps.core.models import User, Configuration
from apps.jobs.models import Job
from apps.jobs.services import BoardService
from apps.jobs.financials import compute_customer_financials
from apps.contacts.services import ContactService
from tests.base import BaseTestCase
from tests.test_contacts_status import make_business, make_job


def archived_job(contact, number, completed_days_ago=3):
    when = timezone.now() - timedelta(days=completed_days_ago)
    return Job.objects.create(job_number=number, contact=contact, status=Job.STATUS_ARCHIVED,
                              created_date=when, start_date=when, completed_date=when)


class ArchivedVisibilityTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        _, self.contact, _ = make_business('VisCo', n_contacts=1)
        self.archived = archived_job(self.contact, 'ARC-V1')
        self.live = make_job(self.contact, Job.STATUS_APPROVED)
        self.done = make_job(self.contact, Job.STATUS_COMPLETED)

    def _ids(self, url):
        return {j['job_id'] for j in self.client.get(url).data['results']}

    def test_open_filter_excludes_archived_and_plain_list_includes_it(self):
        self.assertNotIn(self.archived.pk, self._ids('/api/jobs/?open=true&page_size=100'))
        self.assertIn(self.archived.pk, self._ids('/api/jobs/?page_size=100'))

    def test_exclude_archived_drops_only_archived(self):
        ids = self._ids('/api/jobs/?exclude_archived=true&page_size=100')
        self.assertNotIn(self.archived.pk, ids)
        self.assertIn(self.live.pk, ids)
        self.assertIn(self.done.pk, ids)

    def test_open_jobs_count_excludes_archived(self):
        rollup = compute_customer_financials(self.contact.job_set.all())
        self.assertEqual(rollup['open_jobs'], 1)

    def test_board_closed_lane_includes_recent_archive_and_other_lanes_never_do(self):
        Configuration.objects.update_or_create(key='board_closed_retention_days', defaults={'value': '14'})
        data = BoardService.get_board_data()
        ids = lambda rows: {j['job_id'] for j in rows}
        self.assertIn(self.archived.pk, ids(data['closed']))
        self.assertIn(self.archived.pk, ids(BoardService.get_closed_data()['jobs']))
        self.assertNotIn(self.archived.pk, ids(data['pipeline']))
        self.assertNotIn(self.archived.pk, ids(data['approved']['jobs']))
        self.assertNotIn(self.archived.pk, ids(BoardService.get_unpaid_data()['jobs']))

    def test_contact_with_only_archived_jobs_can_be_deactivated(self):
        # n_contacts=2 so the contact under test is not the business default.
        _, _, others = make_business('OnlyArc', n_contacts=2)
        c = others[0]
        archived_job(c, 'ARC-V2')
        self.assertEqual(ContactService.contact_deactivation_blockers(c), [])
