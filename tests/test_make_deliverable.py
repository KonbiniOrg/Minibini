"""Make Deliverable button (better-fees spec §6, built 2026-08-12):
`DeliverableService.create_from_estimate_line` copies a line's
description/qty/units into a new Deliverable with a `source_line`
provenance FK; the FK suppresses re-offering the button; revising an
estimate RE-POINTS the FK to the copied line (RM decision); deleting a
linked line offers deleting the deliverable too
(`EstimateService.delete_line_item(delete_linked_deliverables=True)`)."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, User
from apps.deliverables.models import Deliverable
from apps.deliverables.services import DeliverableService
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateService
from apps.jobs.models import Job
from tests.base import grant_atoms


class MakeDeliverableBase(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(
            name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001',
            status=Estimate.STATUS_DRAFT,
        )
        self.line = EstimateService.add_line_item(
            self.estimate.pk, description='3 chairs, walnut',
            qty=Decimal('3'), units='ea', price=Decimal('500.00'),
            accounting_category=self.cat.pk,
        )


class CreateFromEstimateLineTest(MakeDeliverableBase):
    def test_copies_description_qty_units_and_links(self):
        d = DeliverableService.create_from_estimate_line(self.line)
        self.assertEqual(d.job, self.job)
        self.assertEqual(d.description, '3 chairs, walnut')
        self.assertEqual(d.qty_ordered, Decimal('3'))
        self.assertEqual(d.units, 'ea')
        self.assertEqual(d.source_line, self.line)

    def test_second_make_on_same_line_is_refused(self):
        DeliverableService.create_from_estimate_line(self.line)
        with self.assertRaises(ValidationError):
            DeliverableService.create_from_estimate_line(self.line)

    def test_refused_when_deliverables_not_editable(self):
        # Send the estimate: open estimates lock the deliverables list.
        Deliverable.objects.create(
            job=self.job, description='existing', qty_ordered=Decimal('1'), units='ea')
        Estimate.objects.filter(pk=self.estimate.pk).update(
            status=Estimate.STATUS_OPEN)
        with self.assertRaises(ValidationError):
            DeliverableService.create_from_estimate_line(self.line)

    def test_deleting_the_deliverable_reoffers(self):
        d = DeliverableService.create_from_estimate_line(self.line)
        DeliverableService.delete(deliverable=d)
        # Link gone with the deliverable — the line is makeable again.
        d2 = DeliverableService.create_from_estimate_line(self.line)
        self.assertEqual(d2.source_line, self.line)


class ReviseRepointsTest(MakeDeliverableBase):
    def test_revise_repoints_source_line_to_the_copied_line(self):
        d = DeliverableService.create_from_estimate_line(self.line)
        Estimate.objects.filter(pk=self.estimate.pk).update(
            status=Estimate.STATUS_OPEN)
        revision = EstimateService.revise_estimate(self.estimate.pk)
        d.refresh_from_db()
        new_line = EstimateLineItem.objects.get(estimate=revision)
        self.assertEqual(d.source_line, new_line)
        self.assertNotEqual(d.source_line_id, self.line.pk)


class DeleteLineWithDeliverableTest(MakeDeliverableBase):
    def test_default_delete_keeps_deliverable_unlinked(self):
        d = DeliverableService.create_from_estimate_line(self.line)
        EstimateService.delete_line_item(self.line.pk)
        d.refresh_from_db()
        self.assertIsNone(d.source_line)

    def test_delete_with_flag_removes_deliverable_too(self):
        d = DeliverableService.create_from_estimate_line(self.line)
        EstimateService.delete_line_item(
            self.line.pk, delete_linked_deliverables=True)
        self.assertFalse(Deliverable.objects.filter(pk=d.pk).exists())


class MakeDeliverableAPITest(MakeDeliverableBase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.manager = grant_atoms(
            User.objects.create_user(username='mkdel_mgr', password='x'),
            'can_manage_jobs')
        self.worker = User.objects.create_user(username='mkdel_wkr', password='x')

    def _url(self, line):
        return (f'/api/estimates/{self.estimate.pk}'
                f'/line-items/{line.pk}/make-deliverable/')

    def test_post_creates_and_serializes(self):
        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(self._url(self.line))
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['description'], '3 chairs, walnut')
        d = Deliverable.objects.get(pk=resp.data['id'])
        self.assertEqual(d.source_line, self.line)

    def test_requires_manage_permission(self):
        self.client.force_authenticate(user=self.worker)
        resp = self.client.post(self._url(self.line))
        self.assertEqual(resp.status_code, 403)

    def test_line_serializer_exposes_linked_deliverables(self):
        self.client.force_authenticate(user=self.manager)
        d = DeliverableService.create_from_estimate_line(self.line)
        resp = self.client.get(f'/api/estimates/{self.estimate.pk}/')
        li = next(x for x in resp.data['line_items']
                  if x['line_item_id'] == self.line.pk)
        self.assertEqual(len(li['linked_deliverables']), 1)
        self.assertEqual(li['linked_deliverables'][0]['id'], d.pk)
        self.assertEqual(li['linked_deliverables'][0]['qty_ordered'], '3.00')
        self.assertEqual(li['linked_deliverables'][0]['units'], 'ea')

    def test_delete_line_with_param_deletes_deliverable(self):
        self.client.force_authenticate(user=self.manager)
        d = DeliverableService.create_from_estimate_line(self.line)
        resp = self.client.delete(
            f'/api/estimates/{self.estimate.pk}/line-items/{self.line.pk}/'
            f'?delete_deliverables=true')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(Deliverable.objects.filter(pk=d.pk).exists())

    def test_delete_line_without_param_keeps_deliverable(self):
        self.client.force_authenticate(user=self.manager)
        d = DeliverableService.create_from_estimate_line(self.line)
        resp = self.client.delete(
            f'/api/estimates/{self.estimate.pk}/line-items/{self.line.pk}/')
        self.assertEqual(resp.status_code, 200, resp.data)
        d.refresh_from_db()
        self.assertIsNone(d.source_line)
