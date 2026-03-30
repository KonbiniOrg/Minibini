"""Tests for contacts services."""

from django.test import TestCase
from django.core.exceptions import ValidationError

from apps.contacts.models import Contact, Business
from apps.contacts.services import ContactService
from apps.core.services import NotFoundError


class ContactServiceCreateTest(TestCase):
    """Tests for ContactService.create_contact."""

    def test_create_contact_minimal(self):
        contact = ContactService.create_contact(
            first_name='John', last_name='Doe',
            email='john@example.com', work_number='555-1234',
        )
        self.assertEqual(contact.first_name, 'John')
        self.assertEqual(contact.last_name, 'Doe')
        self.assertEqual(contact.email, 'john@example.com')
        self.assertIsNone(contact.business)

    def test_create_contact_with_business(self):
        # Need a contact for the business default_contact
        default = Contact.objects.create(
            first_name='Default', last_name='User',
            email='default@example.com', work_number='555-0000',
        )
        biz = Business.objects.create(
            business_name='Acme Corp', default_contact=default,
        )
        default.business = biz
        default.save()

        contact = ContactService.create_contact(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-5678',
            business_pk=biz.pk,
        )
        self.assertEqual(contact.business, biz)

    def test_create_contact_invalid_business_raises(self):
        with self.assertRaises(NotFoundError):
            ContactService.create_contact(
                first_name='Jane', last_name='Doe',
                email='jane@example.com', work_number='555-1234',
                business_pk=99999,
            )

    def test_create_contact_no_phone_raises(self):
        with self.assertRaises(ValidationError):
            ContactService.create_contact(
                first_name='John', last_name='Doe',
                email='john@example.com',
            )


class ContactServiceUpdateTest(TestCase):
    """Tests for ContactService.update_contact."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='John', last_name='Doe',
            email='john@example.com', work_number='555-1234',
        )

    def test_update_contact_fields(self):
        updated = ContactService.update_contact(
            self.contact.pk, first_name='Jane', email='jane@example.com',
        )
        self.assertEqual(updated.first_name, 'Jane')
        self.assertEqual(updated.email, 'jane@example.com')
        # Unchanged fields preserved
        self.assertEqual(updated.last_name, 'Doe')

    def test_update_contact_not_found(self):
        with self.assertRaises(NotFoundError):
            ContactService.update_contact(99999, first_name='X')

    def test_update_contact_change_business(self):
        default = Contact.objects.create(
            first_name='Default', last_name='User',
            email='default@example.com', work_number='555-0000',
        )
        biz = Business.objects.create(
            business_name='Acme', default_contact=default,
        )
        default.business = biz
        default.save()

        updated = ContactService.update_contact(
            self.contact.pk, business_pk=biz.pk,
        )
        self.assertEqual(updated.business, biz)


class ContactServiceDeleteTest(TestCase):
    """Tests for ContactService.delete_contact."""

    def test_delete_unassociated_contact(self):
        contact = Contact.objects.create(
            first_name='John', last_name='Doe',
            email='john@example.com', work_number='555-1234',
        )
        ContactService.delete_contact(contact.pk)
        self.assertFalse(Contact.objects.filter(pk=contact.pk).exists())

    def test_delete_not_found(self):
        with self.assertRaises(NotFoundError):
            ContactService.delete_contact(99999)

    def test_delete_default_contact_auto_reassigns(self):
        c1 = Contact.objects.create(
            first_name='A', last_name='A',
            email='a@example.com', work_number='555-1111',
        )
        c2 = Contact.objects.create(
            first_name='B', last_name='B',
            email='b@example.com', work_number='555-2222',
        )
        biz = Business.objects.create(
            business_name='Acme', default_contact=c1,
        )
        c1.business = biz
        c1.save()
        c2.business = biz
        c2.save()

        # Delete the default — should reassign to c2
        ContactService.delete_contact(c1.pk)
        biz.refresh_from_db()
        self.assertEqual(biz.default_contact, c2)

    def test_delete_default_with_explicit_new_default(self):
        c1 = Contact.objects.create(
            first_name='A', last_name='A',
            email='a@example.com', work_number='555-1111',
        )
        c2 = Contact.objects.create(
            first_name='B', last_name='B',
            email='b@example.com', work_number='555-2222',
        )
        c3 = Contact.objects.create(
            first_name='C', last_name='C',
            email='c@example.com', work_number='555-3333',
        )
        biz = Business.objects.create(
            business_name='Acme', default_contact=c1,
        )
        for c in [c1, c2, c3]:
            c.business = biz
            c.save()

        ContactService.delete_contact(c1.pk, new_default_contact_pk=c3.pk)
        biz.refresh_from_db()
        self.assertEqual(biz.default_contact, c3)

    def test_delete_sole_contact_raises(self):
        c = Contact.objects.create(
            first_name='Solo', last_name='Contact',
            email='solo@example.com', work_number='555-9999',
        )
        biz = Business.objects.create(
            business_name='Lonely Inc', default_contact=c,
        )
        c.business = biz
        c.save()

        with self.assertRaises(ValidationError):
            ContactService.delete_contact(c.pk)

    def test_delete_contact_with_jobs_raises(self):
        from apps.jobs.models import Job
        c = Contact.objects.create(
            first_name='Busy', last_name='Person',
            email='busy@example.com', work_number='555-7777',
        )
        Job.objects.create(
            job_number='JOB-TEST-001', name='Test Job',
            contact=c, status=Job.STATUS_DRAFT,
        )

        with self.assertRaises(ValidationError):
            ContactService.delete_contact(c.pk)


class BusinessServiceCreateTest(TestCase):
    """Tests for ContactService.create_business."""

    def test_create_business_with_contacts(self):
        contacts_data = [
            {
                'first_name': 'John', 'last_name': 'Doe',
                'email': 'john@example.com', 'work_number': '555-1234',
            },
            {
                'first_name': 'Jane', 'last_name': 'Doe',
                'email': 'jane@example.com', 'mobile_number': '555-5678',
            },
        ]
        biz = ContactService.create_business(
            contacts_data, business_name='Acme Corp',
        )
        self.assertEqual(biz.business_name, 'Acme Corp')
        self.assertEqual(biz.contacts.count(), 2)
        # First contact is default
        self.assertEqual(biz.default_contact.first_name, 'John')

    def test_create_business_no_contacts_raises(self):
        with self.assertRaises(ValidationError):
            ContactService.create_business(
                [], business_name='Empty Corp',
            )

    def test_create_business_generates_reference_code(self):
        contacts_data = [
            {
                'first_name': 'A', 'last_name': 'B',
                'email': 'a@b.com', 'work_number': '555',
            },
        ]
        biz = ContactService.create_business(
            contacts_data, business_name='Test Co',
        )
        self.assertTrue(biz.our_reference_code.startswith('BUS-'))


class BusinessServiceCreateForContactTest(TestCase):
    """Tests for ContactService.create_business_for_contact."""

    def test_create_business_for_contact(self):
        contact = Contact.objects.create(
            first_name='John', last_name='Doe',
            email='john@example.com', work_number='555-1234',
        )
        biz = ContactService.create_business_for_contact(
            contact.pk, business_name='New Corp',
        )
        contact.refresh_from_db()
        self.assertEqual(contact.business, biz)
        self.assertEqual(biz.default_contact, contact)

    def test_create_business_for_missing_contact_raises(self):
        with self.assertRaises(NotFoundError):
            ContactService.create_business_for_contact(
                99999, business_name='Nope',
            )


class BusinessServiceUpdateTest(TestCase):
    """Tests for ContactService.update_business."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='A', last_name='B',
            email='a@b.com', work_number='555',
        )
        self.biz = Business.objects.create(
            business_name='Old Name', default_contact=self.contact,
        )
        self.contact.business = self.biz
        self.contact.save()

    def test_update_business(self):
        updated = ContactService.update_business(
            self.biz.pk, business_name='New Name',
            business_phone='555-9999',
        )
        self.assertEqual(updated.business_name, 'New Name')
        self.assertEqual(updated.business_phone, '555-9999')

    def test_update_business_not_found(self):
        with self.assertRaises(NotFoundError):
            ContactService.update_business(99999, business_name='X')


class SetDefaultContactTest(TestCase):
    """Tests for ContactService.set_default_contact."""

    def setUp(self):
        self.c1 = Contact.objects.create(
            first_name='A', last_name='A',
            email='a@a.com', work_number='555',
        )
        self.c2 = Contact.objects.create(
            first_name='B', last_name='B',
            email='b@b.com', work_number='555',
        )
        self.biz = Business.objects.create(
            business_name='Biz', default_contact=self.c1,
        )
        self.c1.business = self.biz
        self.c1.save()
        self.c2.business = self.biz
        self.c2.save()

    def test_set_default_contact(self):
        ContactService.set_default_contact(self.biz.pk, self.c2.pk)
        self.biz.refresh_from_db()
        self.assertEqual(self.biz.default_contact, self.c2)

    def test_set_default_contact_wrong_business_raises(self):
        other = Contact.objects.create(
            first_name='X', last_name='X',
            email='x@x.com', work_number='555',
        )
        with self.assertRaises(ValidationError):
            ContactService.set_default_contact(self.biz.pk, other.pk)


class DeleteBusinessTest(TestCase):
    """Tests for ContactService.delete_business."""

    def test_delete_unassociated_business(self):
        c = Contact.objects.create(
            first_name='A', last_name='B',
            email='a@b.com', work_number='555',
        )
        biz = Business.objects.create(
            business_name='Empty', default_contact=c,
        )
        c.business = biz
        c.save()

        # Even a business with contacts needs actions
        ContactService.delete_business(
            biz.pk,
            contact_actions={c.pk: ('unlink', None)},
        )
        self.assertFalse(Business.objects.filter(pk=biz.pk).exists())
        c.refresh_from_db()
        self.assertIsNone(c.business)

    def test_delete_business_reassign_contacts(self):
        c1 = Contact.objects.create(
            first_name='A', last_name='A',
            email='a@a.com', work_number='555',
        )
        c2 = Contact.objects.create(
            first_name='B', last_name='B',
            email='b@b.com', work_number='555',
        )
        biz1 = Business.objects.create(
            business_name='Source', default_contact=c1,
        )
        c1.business = biz1
        c1.save()

        biz2 = Business.objects.create(
            business_name='Target', default_contact=c2,
        )
        c2.business = biz2
        c2.save()

        ContactService.delete_business(
            biz1.pk,
            contact_actions={c1.pk: ('reassign', biz2)},
        )
        self.assertFalse(Business.objects.filter(pk=biz1.pk).exists())
        c1.refresh_from_db()
        self.assertEqual(c1.business, biz2)

    def test_delete_business_delete_contacts(self):
        c = Contact.objects.create(
            first_name='A', last_name='B',
            email='a@b.com', work_number='555',
        )
        biz = Business.objects.create(
            business_name='Gone', default_contact=c,
        )
        c.business = biz
        c.save()

        ContactService.delete_business(
            biz.pk,
            contact_actions={c.pk: ('delete', None)},
        )
        self.assertFalse(Business.objects.filter(pk=biz.pk).exists())
        self.assertFalse(Contact.objects.filter(pk=c.pk).exists())

    def test_delete_business_not_found(self):
        with self.assertRaises(NotFoundError):
            ContactService.delete_business(99999)

    def test_delete_business_with_pos_reassign(self):
        from apps.purchasing.models import PurchaseOrder
        c1 = Contact.objects.create(
            first_name='A', last_name='A',
            email='a@a.com', work_number='555',
        )
        c2 = Contact.objects.create(
            first_name='B', last_name='B',
            email='b@b.com', work_number='555',
        )
        biz1 = Business.objects.create(
            business_name='Source', default_contact=c1,
        )
        c1.business = biz1
        c1.save()
        biz2 = Business.objects.create(
            business_name='Target', default_contact=c2,
        )
        c2.business = biz2
        c2.save()

        po = PurchaseOrder.objects.create(
            business=biz1, status=PurchaseOrder.STATUS_DRAFT, po_number='PO-TEST-001',
        )

        ContactService.delete_business(
            biz1.pk,
            po_actions={po.pk: ('reassign', biz2)},
            contact_actions={c1.pk: ('unlink', None)},
        )
        po.refresh_from_db()
        self.assertEqual(po.business, biz2)
        self.assertFalse(Business.objects.filter(pk=biz1.pk).exists())

    def test_delete_business_with_jobs_reassign(self):
        from apps.jobs.models import Job
        c1 = Contact.objects.create(
            first_name='A', last_name='A',
            email='a@a.com', work_number='555',
        )
        c2 = Contact.objects.create(
            first_name='B', last_name='B',
            email='b@b.com', work_number='555',
        )
        biz = Business.objects.create(
            business_name='Source', default_contact=c1,
        )
        c1.business = biz
        c1.save()

        job = Job.objects.create(
            job_number='JOB-TEST-002', name='Test',
            contact=c1, status=Job.STATUS_DRAFT,
        )

        ContactService.delete_business(
            biz.pk,
            contact_actions={c1.pk: ('delete', None)},
            job_actions={job.pk: ('reassign', c2.pk)},
        )
        job.refresh_from_db()
        self.assertEqual(job.contact, c2)
