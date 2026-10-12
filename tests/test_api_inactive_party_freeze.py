# tests/test_api_inactive_party_freeze.py
"""A job whose contact is inactive is frozen (spec §5): every user-driven
mutation answers 400 with the freeze sentence; the same-business contact
swap is the one exception; Duplicate still works."""
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, AccountingCategory
from apps.contacts.models import Contact
from apps.contacts.services import ContactService
from apps.jobs.models import Job, Task, RateScheme
from tests.test_contacts_status import make_business, make_job

FREEZE = 'is inactive'


class JobFreezeTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        self.biz, self.dc, (self.other,) = make_business('FrzCo')
        self.job = make_job(self.other, Job.STATUS_CANCELLED)   # closed → deactivation allowed
        self.scheme = RateScheme.objects.first()
        self.task = Task(job=self.job, name='T', status=Task.STATUS_PENDING)
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()
        ContactService.deactivate_contact(self.other)
        self.job.refresh_from_db()

    def _assert_frozen(self, response):
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(FREEZE, response.data.get('detail', ''))

    def test_serializer_flags(self):
        d = self.client.get(f'/api/jobs/{self.job.pk}/').data
        self.assertFalse(d['contact_is_active'])
        self.assertEqual(d['contact_business_name'], 'FrzCo')
        self.assertEqual(d['contact_business_id'], self.biz.pk)
        self.assertTrue(d['contact_business_is_active'])

    def test_field_edit_refused(self):
        self._assert_frozen(self.client.patch(f'/api/jobs/{self.job.pk}/', {'name': 'x'}, format='json'))

    def test_reopen_refused(self):
        self._assert_frozen(self.client.patch(f'/api/jobs/{self.job.pk}/', {'status': Job.STATUS_IN_PROGRESS}, format='json'))

    def test_note_refused(self):
        self._assert_frozen(self.client.post(f'/api/jobs/{self.job.pk}/notes/', {'text': 'n'}, format='json'))

    def test_task_add_edit_delete_refused(self):
        self._assert_frozen(self.client.post(f'/api/jobs/{self.job.pk}/tasks/', {'name': 'New', 'rate_scheme': self.scheme.pk}, format='json'))
        self._assert_frozen(self.client.patch(f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/', {'name': 'x'}, format='json'))
        self._assert_frozen(self.client.delete(f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/'))

    def test_delete_job_refused(self):
        self._assert_frozen(self.client.delete(f'/api/jobs/{self.job.pk}/'))

    def test_material_add_refused(self):
        self._assert_frozen(self.client.post(f'/api/jobs/{self.job.pk}/materials/',
                                             {'description': 'm', 'quantity': '1.00', 'units': 'none', 'unit_cost': '5.00',
                                              'sell_price': '10.00', 'accounting_category': AccountingCategory.objects.first().pk}, format='json'))

    def test_swap_to_same_business_active_contact_unfreezes(self):
        r = self.client.patch(f'/api/jobs/{self.job.pk}/', {'contact': self.dc.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['contact_is_active'])
        # now a normal edit works
        self.assertEqual(self.client.patch(f'/api/jobs/{self.job.pk}/', {'name': 'thawed'}, format='json').status_code, 200)

    def test_swap_plus_other_field_refused(self):
        self._assert_frozen(self.client.patch(f'/api/jobs/{self.job.pk}/', {'contact': self.dc.pk, 'name': 'x'}, format='json'))

    def test_swap_to_same_inactive_contact_refused(self):
        r = self.client.patch(f'/api/jobs/{self.job.pk}/', {'contact': self.other.pk}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_swap_to_other_business_refused(self):
        stranger = Contact.objects.create(first_name='S', last_name='T', email='st@x.test')
        self._assert_frozen(self.client.patch(f'/api/jobs/{self.job.pk}/', {'contact': stranger.pk}, format='json'))

    def test_swap_refused_when_business_inactive(self):
        # Reactivate `other` so we can deactivate the whole business cleanly, then re-check.
        ContactService.reactivate_contact(self.other)
        ContactService.deactivate_business(self.biz)
        r = self.client.patch(f'/api/jobs/{self.job.pk}/', {'contact': self.dc.pk}, format='json')
        # new contact is inactive via its business: party-active field error (400)
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn('contact', r.data)

    def test_duplicate_allowed_with_active_contact(self):
        live = Contact.objects.create(first_name='L', last_name='V', email='lv@x.test')
        r = self.client.post(f'/api/jobs/{self.job.pk}/duplicate/', {'contact_id': live.pk, 'path': 'estimate'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def test_system_transition_bypasses(self):
        from apps.jobs.services import JobService
        JobService.update_job(self.job.pk, system_transition=True, status=Job.STATUS_IN_PROGRESS)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)


class JobContactSwapModelTest(BaseTestCase):
    """Job.clean: contact is immutable after draft, except the inactive-contact escape."""
    def setUp(self):
        super().setUp()
        self.biz, self.dc, (self.other,) = make_business('MdlCo')
        self.job = make_job(self.other, Job.STATUS_COMPLETED)

    def _swap(self, contact):
        job = Job.objects.get(pk=self.job.pk)
        job.contact = contact
        job.full_clean()
        job.save()

    def test_active_old_contact_refuses_change(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self._swap(self.dc)

    def test_inactive_old_same_business_allowed(self):
        ContactService.deactivate_contact(self.other)
        self._swap(self.dc)
        self.assertEqual(Job.objects.get(pk=self.job.pk).contact_id, self.dc.pk)

    def test_cross_business_refused(self):
        from django.core.exceptions import ValidationError
        ContactService.deactivate_contact(self.other)
        stranger = Contact.objects.create(first_name='S', last_name='T', email='st2@x.test')
        with self.assertRaises(ValidationError):
            self._swap(stranger)


class DocumentFreezeTest(BaseTestCase):
    """One representative endpoint per document service; the service-level
    guard covers the rest of each service's entry points."""
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        self.biz, self.dc, (self.other,) = make_business('DocCo')
        self.job = make_job(self.other, Job.STATUS_COMPLETED)
        ContactService.deactivate_contact(self.other)

    def _assert_frozen(self, response):
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(FREEZE, response.data.get('detail', ''))

    def test_estimate_create_refused(self):
        self._assert_frozen(self.client.post('/api/estimates/', {'job': self.job.pk}, format='json'))

    def test_change_order_create_refused(self):
        self._assert_frozen(self.client.post('/api/change-orders/', {'job': self.job.pk}, format='json'))

    def test_deliverable_create_refused(self):
        self._assert_frozen(self.client.post(f'/api/jobs/{self.job.pk}/deliverables/',
                                             {'description': 'd', 'qty_ordered': '1', 'units': 'ea'}, format='json'))

    def test_shipment_create_refused(self):
        self._assert_frozen(self.client.post(f'/api/jobs/{self.job.pk}/shipments/', {}, format='json'))

    def test_invoice_open_refused(self):
        self._assert_frozen(self.client.post(f'/api/jobs/{self.job.pk}/start-invoice-wizard/', {}, format='json'))


class DocumentFreezeBypassAndFunnelTest(BaseTestCase):
    """Behaviour of the guard beyond the create paths: system bypass,
    the shared wizard funnel, and the customer portal.

    The documents are built while the contact is active; the contact is then
    forced inactive with a queryset update (test-only — open jobs normally
    block deactivation, so this reaches the frozen-with-live-document state
    the guard must handle generically)."""
    def setUp(self):
        super().setUp()
        from decimal import Decimal
        from apps.estimates.models import Estimate, EstimateLineItem
        from apps.estimates.services import EstimateService
        from apps.jobs.services import JobService
        self.contact = Contact.objects.create(first_name='Pat', last_name='Frz', email='patfrz@x.test')
        self.job = JobService.create_job(name='Frz Job', contact=self.contact)
        self.est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(
            estimate=self.est, description='Work', qty=Decimal('1'), price=Decimal('100.00'),
            accounting_category=AccountingCategory.objects.filter(is_deposit=False).first())

    def _freeze(self):
        Contact.objects.filter(pk=self.contact.pk).update(is_active=False)

    def _open_estimate(self):
        from apps.estimates.models import Estimate
        from apps.estimates.services import EstimateService
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        self.est.refresh_from_db()

    def test_estimate_update_status_refused_but_system_transition_allowed(self):
        from django.core.exceptions import ValidationError
        from apps.estimates.models import Estimate
        from apps.estimates.services import EstimateService
        self._open_estimate()
        self._freeze()
        with self.assertRaises(ValidationError) as cm:
            EstimateService.update_status(self.est.pk, Estimate.STATUS_EXPIRED)
        self.assertIn(FREEZE, str(cm.exception))
        EstimateService.update_status(self.est.pk, Estimate.STATUS_EXPIRED, system_transition=True)
        self.est.refresh_from_db()
        self.assertEqual(self.est.status, Estimate.STATUS_EXPIRED)

    def test_change_order_update_status_refused_but_system_transition_allowed(self):
        from django.core.exceptions import ValidationError
        from apps.estimates.change_order_service import ChangeOrderService
        from apps.estimates.models import ChangeOrder
        from tests.test_mark_change_orders_expired import (
            _advance_job_to_on_hold, _make_accepted_estimate, _make_open_co_past_due)
        from apps.estimates.models import Estimate
        Estimate.objects.filter(pk=self.est.pk).delete()
        _advance_job_to_on_hold(self.job)
        est = _make_accepted_estimate(self.job)
        co = _make_open_co_past_due(self.job, est)
        self._freeze()
        with self.assertRaises(ValidationError) as cm:
            ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_EXPIRED)
        self.assertIn(FREEZE, str(cm.exception))
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_EXPIRED, system_transition=True)
        co.refresh_from_db()
        self.assertEqual(co.status, ChangeOrder.STATUS_EXPIRED)

    def test_wizard_funnel_refuses_on_frozen_job(self):
        from django.core.exceptions import ValidationError
        from apps.estimates.services import EstimateWizardService
        task = Task(job=self.job, name='T', status=Task.STATUS_PENDING)
        task.stamp_from_scheme(RateScheme.objects.first())
        task.save()
        self._freeze()
        self.est = type(self.est).objects.get(pk=self.est.pk)  # drop the cached active contact
        with self.assertRaises(ValidationError) as cm:
            EstimateWizardService.add_atoms_to_new_line_item(
                self.est, [{'type': 'task', 'id': task.pk}])
        self.assertIn(FREEZE, str(cm.exception))

    def test_portal_accept_refused_on_frozen_job(self):
        from django.test import Client
        from apps.estimates.models import Estimate
        self._open_estimate()
        self._freeze()
        r = Client().post(f'/api/portal/estimates/{self.est.public_token}/accept/')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn(FREEZE, r.json().get('detail', ''))
        self.est.refresh_from_db()
        self.assertEqual(self.est.status, Estimate.STATUS_OPEN)


class POFreezeTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        from apps.purchasing.models import PurchaseOrder
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        self.biz, self.dc, (self.other,) = make_business('PoFrz')
        self.po = PurchaseOrder.objects.create(po_number='PO-FRZ-1', business=self.biz, contact=self.other,
                                               status=PurchaseOrder.STATUS_RECEIVED_IN_FULL)
        ContactService.deactivate_contact(self.other)

    def _assert_frozen(self, response):
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(FREEZE, response.data.get('detail', ''))

    def test_flags_and_edit_refused(self):
        d = self.client.get(f'/api/purchase-orders/{self.po.pk}/').data
        self.assertFalse(d['contact_is_active']); self.assertTrue(d['business_is_active'])
        self._assert_frozen(self.client.patch(f'/api/purchase-orders/{self.po.pk}/', {'requested_date': '2026-11-01'}, format='json'))
        self._assert_frozen(self.client.post(f'/api/purchase-orders/{self.po.pk}/line-items/',
                                             {'description': 'x', 'qty': '1', 'price': '1.00'}, format='json'))

    def test_swap_contact_same_vendor_ok_then_edit_works(self):
        r = self.client.patch(f'/api/purchase-orders/{self.po.pk}/', {'contact': self.dc.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.client.patch(f'/api/purchase-orders/{self.po.pk}/', {'requested_date': '2026-11-01'}, format='json').status_code, 200)

    def test_inactive_vendor_business_freezes_without_swap(self):
        ContactService.reactivate_contact(self.other)
        ContactService.deactivate_business(self.biz)
        self._assert_frozen(self.client.patch(f'/api/purchase-orders/{self.po.pk}/', {'contact': self.dc.pk}, format='json'))
