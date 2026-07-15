"""Service classes for Contact and Business operations."""

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.contacts.models import Contact, Business
from apps.core.services import NotFoundError

# Sentinel for distinguishing "not passed" from None
_sentinel = object()


class ContactService:
    """Service for Contact and Business CRUD operations."""

    # --- Contact CRUD ---

    @staticmethod
    def create_contact(*, business_pk=None, **kwargs):
        """Create a new contact, optionally associated with a business.

        Checks for an existing contact with the same email up front (rather
        than letting the DB unique constraint / full_clean() reject it) so
        the caller can identify *which* contact conflicted and surface a
        "did you mean this one?" prompt instead of a bare validation error.
        """
        email = (kwargs.get('email') or '').strip()
        if email:
            existing = Contact.objects.filter(email__iexact=email).first()
            if existing:
                raise ValidationError(
                    'A contact with this email address already exists.',
                    code='duplicate_email',
                    params={'contact_id': existing.pk},
                )

        business = None
        if business_pk is not None:
            try:
                business = Business.objects.get(pk=business_pk)
            except Business.DoesNotExist:
                raise NotFoundError(f'Business {business_pk} not found')

        contact = Contact(business=business, **kwargs)
        contact.full_clean()
        contact.save()
        return contact

    @staticmethod
    def update_contact(pk, *, business_pk=_sentinel, **kwargs):
        """Update contact fields. Pass business_pk to change business association."""
        try:
            contact = Contact.objects.get(pk=pk)
        except Contact.DoesNotExist:
            raise NotFoundError(f'Contact {pk} not found')

        for field, value in kwargs.items():
            setattr(contact, field, value)

        if business_pk is not _sentinel:
            if business_pk is None:
                contact.business = None
            else:
                try:
                    contact.business = Business.objects.get(pk=business_pk)
                except Business.DoesNotExist:
                    raise NotFoundError(f'Business {business_pk} not found')

        contact.full_clean()
        contact.save()
        return contact

    @staticmethod
    def delete_contact(pk, new_default_contact_pk=None):
        """Delete a contact, handling default_contact reassignment.

        Raises ValidationError if the contact has associated jobs/bills
        or is the sole contact for a business.
        """
        try:
            contact = Contact.objects.get(pk=pk)
        except Contact.DoesNotExist:
            raise NotFoundError(f'Contact {pk} not found')

        # Check for associated jobs
        from apps.jobs.models import Job
        if Job.objects.filter(contact=contact).exists():
            raise ValidationError(
                f'Cannot delete contact "{contact}" because it has associated jobs.'
            )

        # Check for associated bills
        from apps.purchasing.models import Bill
        if Bill.objects.filter(contact=contact).exists():
            raise ValidationError(
                f'Cannot delete contact "{contact}" because it has associated bills.'
            )

        business = contact.business
        if business and business.default_contact == contact:
            other_contacts = business.contacts.exclude(pk=pk)
            if not other_contacts.exists():
                raise ValidationError(
                    f'Cannot delete "{contact}" — it is the only contact for '
                    f'business "{business.business_name}".'
                )

            # Determine new default
            if new_default_contact_pk:
                try:
                    new_default = Contact.objects.get(
                        pk=new_default_contact_pk, business=business,
                    )
                except Contact.DoesNotExist:
                    raise NotFoundError(
                        f'Contact {new_default_contact_pk} not found in business'
                    )
            else:
                new_default = other_contacts.first()

            # Set new default before deleting to avoid PROTECT
            business.default_contact = new_default
            business.save(update_fields=['default_contact'])

        contact.delete()

    # --- Business CRUD ---

    @staticmethod
    def create_business(contacts_data, **kwargs):
        """Create a business with one or more contacts.

        contacts_data: list of dicts with contact field values.
        First contact becomes the default_contact.
        """
        if not contacts_data:
            raise ValidationError('At least one contact is required.')

        with transaction.atomic():
            # Create first contact without business (needed for default_contact FK)
            first_data = contacts_data[0]
            first_contact = Contact(**first_data)
            first_contact.full_clean()
            first_contact.save()

            # Create business with first contact as default
            business = Business(default_contact=first_contact, **kwargs)
            business.full_clean()
            business.save()

            # Link first contact to business
            first_contact.business = business
            first_contact.save()

            # Create remaining contacts
            for data in contacts_data[1:]:
                c = Contact(business=business, **data)
                c.full_clean()
                c.save()

        return business

    @staticmethod
    def create_business_for_contact(contact_pk, **kwargs):
        """Create a new business and link an existing contact as default."""
        try:
            contact = Contact.objects.get(pk=contact_pk)
        except Contact.DoesNotExist:
            raise NotFoundError(f'Contact {contact_pk} not found')

        with transaction.atomic():
            business = Business(default_contact=contact, **kwargs)
            business.full_clean()
            business.save()
            contact.business = business
            contact.save()

        return business

    @staticmethod
    def update_business(pk, **kwargs):
        """Update business fields."""
        try:
            business = Business.objects.get(pk=pk)
        except Business.DoesNotExist:
            raise NotFoundError(f'Business {pk} not found')

        for field, value in kwargs.items():
            setattr(business, field, value)
        business.full_clean()
        business.save()
        return business

    @staticmethod
    def set_default_contact(business_pk, contact_pk):
        """Set a contact as the default for a business."""
        try:
            business = Business.objects.get(pk=business_pk)
        except Business.DoesNotExist:
            raise NotFoundError(f'Business {business_pk} not found')
        try:
            contact = Contact.objects.get(pk=contact_pk)
        except Contact.DoesNotExist:
            raise NotFoundError(f'Contact {contact_pk} not found')
        if contact.business != business:
            raise ValidationError(
                f'Contact "{contact}" is not associated with business '
                f'"{business.business_name}".'
            )
        business.default_contact = contact
        business.save(update_fields=['default_contact'])

    @staticmethod
    def delete_business(pk, po_actions=None, bill_actions=None,
                        contact_actions=None, job_actions=None):
        """Delete a business with cascading reassignment/deletion.

        Actions dicts map object PKs to (action, target) tuples:
        - po_actions: {po_pk: ('delete'|'reassign', target_business|None)}
        - bill_actions: {bill_pk: ('delete'|'reassign', target_business|None)}
        - contact_actions: {contact_pk: ('unlink'|'delete'|'reassign', target_business|None)}
        - job_actions: {job_pk: ('delete'|'reassign', target_contact_pk|None)}
        """
        from apps.jobs.models import Job
        from apps.purchasing.models import PurchaseOrder, Bill

        try:
            business = Business.objects.get(pk=pk)
        except Business.DoesNotExist:
            raise NotFoundError(f'Business {pk} not found')

        po_actions = po_actions or {}
        bill_actions = bill_actions or {}
        contact_actions = contact_actions or {}
        job_actions = job_actions or {}

        contacts = list(business.contacts.all())
        contacts_being_deleted = {
            cid for cid, (action, _) in contact_actions.items()
            if action == 'delete'
        }

        with transaction.atomic():
            # Step 1: Process POs
            for po in PurchaseOrder.objects.filter(business=business):
                action, target = po_actions.get(po.pk, (None, None))
                if action == 'delete':
                    po.delete()
                elif action == 'reassign':
                    PurchaseOrder.objects.filter(pk=po.pk).update(
                        business=target, contact=None,
                    )

            # Step 2: Process Bills
            for bill in Bill.objects.filter(business=business):
                action, target = bill_actions.get(bill.pk, (None, None))
                if action == 'delete':
                    bill.delete()
                elif action == 'reassign':
                    Bill.objects.filter(pk=bill.pk).update(
                        business=target, contact=None,
                    )

            # Step 3: Process Jobs (for contacts being deleted)
            for job_id, (action, target) in job_actions.items():
                if action == 'delete':
                    Job.objects.get(pk=job_id).delete()
                elif action == 'reassign':
                    Job.objects.filter(pk=job_id).update(contact_id=target)

            # Step 4: Clear contact references on POs/Bills from OTHER
            # businesses that reference contacts being deleted
            if contacts_being_deleted:
                PurchaseOrder.objects.filter(
                    contact_id__in=contacts_being_deleted,
                ).update(contact=None)
                Bill.objects.filter(
                    contact_id__in=contacts_being_deleted,
                ).update(contact=None)

            # Step 5: Unlink and reassign contacts
            for contact in contacts:
                cid = contact.contact_id
                action, target = contact_actions.get(cid, (None, None))
                if action == 'unlink':
                    Contact.objects.filter(pk=cid).update(business=None)
                elif action == 'reassign':
                    Contact.objects.filter(pk=cid).update(business=target)

            # Step 6: Delete the business
            business.delete()

            # Step 7: Delete contacts marked for deletion
            if contacts_being_deleted:
                Contact.objects.filter(
                    contact_id__in=contacts_being_deleted,
                ).delete()


class TagService:
    """Owns tag attach/detach for taggable records (Contact, Business).
    get_or_create keeps the global tag list deduplicated by name."""

    @staticmethod
    def attach(obj, name):
        from apps.contacts.models import Tag
        tag, _ = Tag.objects.get_or_create(name=name)
        obj.tags.add(tag)
        return obj.tags.all()

    @staticmethod
    def detach(obj, tag_id):
        obj.tags.remove(tag_id)
        return obj.tags.all()
