# tests/test_contacts_status.py
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Business, Contact
from apps.contacts.services import ContactService, TagService
from apps.invoicing.models import Invoice
from apps.jobs.models import Job
from apps.purchasing.models import PurchaseOrder


def make_business(name='Acme', n_contacts=2):
    dc = Contact.objects.create(first_name='Default', last_name=name, email=f'dc-{name}@x.test')
    b = Business.objects.create(business_name=name, default_contact=dc)
    dc.business = b
    dc.save()
    others = [Contact.objects.create(first_name=f'C{i}', last_name=name, email=f'c{i}-{name}@x.test', business=b)
              for i in range(n_contacts - 1)]
    return b, dc, others


def make_job(contact, status):
    import time
    job = Job.objects.create(job_number=f'J-ST-{time.time():.6f}', contact=contact, status=Job.STATUS_DRAFT)
    walk = {
        Job.STATUS_DRAFT: [], Job.STATUS_SUBMITTED: [Job.STATUS_SUBMITTED],
        Job.STATUS_APPROVED: [Job.STATUS_SUBMITTED, Job.STATUS_APPROVED],
        Job.STATUS_IN_PROGRESS: [Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS],
        Job.STATUS_REJECTED: [Job.STATUS_REJECTED],
        Job.STATUS_CANCELLED: [Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_CANCELLED],
        Job.STATUS_COMPLETED: [Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS,
                               Job.STATUS_WORK_COMPLETE, Job.STATUS_COMPLETED],
    }[status]
    for s in walk:
        job.status = s
        job.save()
    job.refresh_from_db()
    return job


class DeactivateContactTest(TestCase):
    def test_individual_with_no_records_deactivates(self):
        c = Contact.objects.create(first_name='Solo', last_name='X', email='solo@x.test')
        ContactService.deactivate_contact(c)
        c.refresh_from_db()
        self.assertFalse(c.is_active)

    def test_default_contact_of_active_business_blocked(self):
        b, dc, _ = make_business('Dflt')
        with self.assertRaises(ValidationError) as cm:
            ContactService.deactivate_contact(dc)
        self.assertIn('default contact for Dflt', str(cm.exception))
        dc.refresh_from_db()
        self.assertTrue(dc.is_active)

    def test_non_default_contact_of_active_business_deactivates(self):
        b, dc, (other,) = make_business('Ok')
        ContactService.deactivate_contact(other)
        other.refresh_from_db()
        self.assertFalse(other.is_active)
        b.refresh_from_db()
        self.assertTrue(b.is_active)

    def test_open_job_blocks_and_names_it(self):
        c = Contact.objects.create(first_name='Busy', last_name='X', email='busy@x.test')
        job = make_job(c, Job.STATUS_IN_PROGRESS)
        with self.assertRaises(ValidationError) as cm:
            ContactService.deactivate_contact(c)
        msg = str(cm.exception)
        self.assertIn('1 open job', msg)
        self.assertIn(job.job_number, msg)

    def test_closed_job_does_not_block(self):
        c = Contact.objects.create(first_name='Done', last_name='X', email='done@x.test')
        make_job(c, Job.STATUS_COMPLETED)
        ContactService.deactivate_contact(c)
        c.refresh_from_db()
        self.assertFalse(c.is_active)

    def test_open_invoice_on_closed_job_blocks(self):
        c = Contact.objects.create(first_name='Inv', last_name='X', email='inv@x.test')
        job = make_job(c, Job.STATUS_COMPLETED)
        Invoice.objects.create(job=job, status=Invoice.STATUS_OPEN)
        with self.assertRaises(ValidationError) as cm:
            ContactService.deactivate_contact(c)
        self.assertIn('1 open invoice', str(cm.exception))

    def test_open_po_as_vendor_contact_blocks(self):
        b, dc, (other,) = make_business('Vend')
        PurchaseOrder.objects.create(po_number='PO-ST-1', business=b, contact=other,
                                     status=PurchaseOrder.STATUS_ISSUED)
        with self.assertRaises(ValidationError) as cm:
            ContactService.deactivate_contact(other)
        self.assertIn('1 open PO', str(cm.exception))

    def test_all_blockers_in_one_sentence(self):
        b, dc, _ = make_business('Multi')
        job = make_job(dc, Job.STATUS_DRAFT)
        with self.assertRaises(ValidationError) as cm:
            ContactService.deactivate_contact(dc)
        msg = str(cm.exception)
        self.assertIn('default contact for Multi', msg)
        self.assertIn('1 open job', msg)
        self.assertTrue(cm.exception.messages[0].startswith('Cannot deactivate'))

    def test_already_inactive_is_noop(self):
        c = Contact.objects.create(first_name='Twice', last_name='X', email='twice@x.test', is_active=False)
        make_job(c, Job.STATUS_DRAFT)          # would block if evaluated
        ContactService.deactivate_contact(c)   # no error
        c.refresh_from_db()
        self.assertFalse(c.is_active)


class ReactivateContactTest(TestCase):
    def test_reactivate_under_inactive_business_blocked(self):
        b, dc, (other,) = make_business('Dead')
        ContactService.deactivate_business(b)
        other.refresh_from_db()
        with self.assertRaises(ValidationError) as cm:
            ContactService.reactivate_contact(other)
        self.assertIn('business Dead is inactive', str(cm.exception))

    def test_reactivate_individual(self):
        c = Contact.objects.create(first_name='Back', last_name='X', email='back@x.test', is_active=False)
        ContactService.reactivate_contact(c)
        c.refresh_from_db()
        self.assertTrue(c.is_active)


class BusinessStatusTest(TestCase):
    def test_deactivate_cascades_and_reactivate_restores_all(self):
        b, dc, (other,) = make_business('Casc')
        other.is_active = False          # individually inactive beforehand
        other.save()
        ContactService.deactivate_business(b)
        for o in (b, dc, other):
            o.refresh_from_db()
        self.assertFalse(b.is_active); self.assertFalse(dc.is_active); self.assertFalse(other.is_active)
        ContactService.reactivate_business(b)
        for o in (b, dc, other):
            o.refresh_from_db()
        self.assertTrue(b.is_active); self.assertTrue(dc.is_active)
        self.assertTrue(other.is_active)   # symmetric cascade (spec §4.5)

    def test_default_contact_rule_does_not_apply_to_business(self):
        b, dc, _ = make_business('NoDflt')
        ContactService.deactivate_business(b)
        b.refresh_from_db()
        self.assertFalse(b.is_active)

    def test_open_job_on_any_contact_blocks(self):
        b, dc, (other,) = make_business('Blk')
        make_job(other, Job.STATUS_APPROVED)
        with self.assertRaises(ValidationError) as cm:
            ContactService.deactivate_business(b)
        self.assertIn('1 open job', str(cm.exception))

    def test_open_vendor_po_blocks(self):
        b, dc, _ = make_business('VendB')
        PurchaseOrder.objects.create(po_number='PO-ST-2', business=b, status=PurchaseOrder.STATUS_DRAFT)
        with self.assertRaises(ValidationError) as cm:
            ContactService.deactivate_business(b)
        self.assertIn('1 open PO', str(cm.exception))

    def test_impact_payload(self):
        b, dc, (other,) = make_business('Imp')
        make_job(dc, Job.STATUS_DRAFT)
        impact = ContactService.deactivate_business_impact(b)
        self.assertEqual(impact['contact_count'], 2)
        self.assertEqual(sorted(impact['contact_names']), sorted([dc.name, other.name]))
        self.assertEqual(len(impact['blockers']), 1)
        self.assertIn('1 open job', impact['blockers'][0])

    def test_history_records_the_flip(self):
        from apps.core.models import CrmHistory
        b, dc, _ = make_business('Hist')
        ContactService.deactivate_business(b)
        entries = CrmHistory.objects.filter(object_type='business', object_id=b.pk)
        self.assertTrue(any('is_active' in (e.changes or {}) for e in entries))


class InactiveEditRefusalTest(TestCase):
    def setUp(self):
        self.c = Contact.objects.create(first_name='Frozen', last_name='X', email='fz@x.test', is_active=False)
        b, dc, _ = make_business('FrozenCo')
        ContactService.deactivate_business(b)
        self.b = b

    def test_update_contact_refused(self):
        with self.assertRaises(ValidationError) as cm:
            ContactService.update_contact(self.c.pk, first_name='New')
        self.assertIn('is inactive', str(cm.exception))

    def test_update_business_refused(self):
        with self.assertRaises(ValidationError):
            ContactService.update_business(self.b.pk, website='https://x.test')

    def test_set_default_contact_refused(self):
        other = Contact.objects.create(first_name='O', last_name='X', email='o@x.test', business=self.b, is_active=False)
        with self.assertRaises(ValidationError):
            ContactService.set_default_contact(self.b.pk, other.pk)

    def test_tags_refused(self):
        with self.assertRaises(ValidationError):
            TagService.attach(self.c, 'vip')
        with self.assertRaises(ValidationError):
            TagService.detach(self.c, 1)

    def test_note_refused(self):
        with self.assertRaises(ValidationError):
            ContactService.add_note(self.c, 'contact', 'hello')

    def test_delete_still_allowed(self):
        ContactService.delete_contact(self.c.pk)
        self.assertFalse(Contact.objects.filter(pk=self.c.pk).exists())


class CreateWithInactivePartyTest(TestCase):
    def test_create_job_with_inactive_contact(self):
        from apps.jobs.services import JobService
        c = Contact.objects.create(first_name='In', last_name='X', email='in@x.test', is_active=False)
        with self.assertRaises(ValidationError) as cm:
            JobService.create_job(name='J', contact=c)
        self.assertIn('contact', cm.exception.message_dict)

    def test_create_job_with_contact_of_inactive_business(self):
        from apps.jobs.services import JobService
        b, dc, _ = make_business('InCo')
        b.is_active = False
        b.save()                      # contact stays active: business branch only
        dc.refresh_from_db()
        self.assertTrue(dc.is_active)
        with self.assertRaises(ValidationError) as cm:
            JobService.create_job(name='J', contact=dc)
        self.assertIn('InCo is inactive.', cm.exception.message_dict['contact'][0])

    def test_create_job_with_contact_of_cascade_deactivated_business(self):
        from apps.jobs.services import JobService
        b, dc, _ = make_business('InCo2')
        ContactService.deactivate_business(b)
        dc.refresh_from_db()
        with self.assertRaises(ValidationError) as cm:
            JobService.create_job(name='J', contact=dc)
        self.assertIn('contact', cm.exception.message_dict)

    def test_duplicate_into_inactive_contact_refused_but_frozen_source_ok(self):
        from apps.jobs.services import JobService
        src_contact = Contact.objects.create(first_name='Src', last_name='X', email='src@x.test')
        src = make_job(src_contact, Job.STATUS_COMPLETED)
        ContactService.deactivate_contact(src_contact)       # source now frozen
        dead = Contact.objects.create(first_name='Dead', last_name='Y', email='deady@x.test', is_active=False)
        with self.assertRaises(ValidationError):
            JobService.duplicate_job(src, contact=dead, path='estimate')
        live = Contact.objects.create(first_name='Live', last_name='Y', email='livey@x.test')
        new = JobService.duplicate_job(src, contact=live, path='estimate')
        self.assertEqual(new.contact, live)

    def test_create_po_with_inactive_vendor_or_contact(self):
        from apps.purchasing.services import PurchaseOrderService
        b, dc, (other,) = make_business('PoCo')
        ContactService.deactivate_contact(other)
        with self.assertRaises(ValidationError) as cm:
            PurchaseOrderService.create_po(business=b, contact=other)
        self.assertIn('contact', cm.exception.message_dict)
        ContactService.deactivate_business(b)
        with self.assertRaises(ValidationError) as cm:
            PurchaseOrderService.create_po(business=b)
        self.assertIn('business', cm.exception.message_dict)


class InactiveBusinessAttachTest(TestCase):
    def _inactive_business(self):
        b, dc, _ = make_business('DeadCo')
        ContactService.deactivate_business(b)
        b.refresh_from_db()
        return b

    def test_create_contact_into_inactive_business_refused(self):
        b = self._inactive_business()
        with self.assertRaises(ValidationError) as cm:
            ContactService.create_contact(business_pk=b.pk, first_name='N', last_name='X', email='nx@x.test')
        self.assertIn('DeadCo is inactive.', cm.exception.message_dict['business_id'][0])

    def test_update_contact_move_into_inactive_business_refused(self):
        b = self._inactive_business()
        c = Contact.objects.create(first_name='M', last_name='X', email='mx@x.test')
        with self.assertRaises(ValidationError) as cm:
            ContactService.update_contact(c.pk, business_pk=b.pk)
        self.assertIn('business_id', cm.exception.message_dict)


class InactiveDefaultContactTest(TestCase):
    def test_update_business_default_to_inactive_contact_refused(self):
        b, dc, (other,) = make_business('DefCo')
        ContactService.deactivate_contact(other)
        other.refresh_from_db()
        with self.assertRaises(ValidationError) as cm:
            ContactService.update_business(b.pk, default_contact=other)
        self.assertIn('is inactive', str(cm.exception))
