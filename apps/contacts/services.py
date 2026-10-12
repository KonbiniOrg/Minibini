"""Service classes for Contact and Business operations."""

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.contacts.models import Contact, Business
from apps.core.history import record_history
from apps.core.services import NotFoundError



def _open_statuses():
    from apps.invoicing.models import Invoice
    from apps.jobs.models import Job
    from apps.purchasing.models import PurchaseOrder
    return (
        (Job.STATUS_DRAFT, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
         Job.STATUS_IN_PROGRESS, Job.STATUS_WORK_COMPLETE),
        (Invoice.STATUS_DRAFT, Invoice.STATUS_OPEN, Invoice.STATUS_PARTLY_PAID),
        (PurchaseOrder.STATUS_DRAFT, PurchaseOrder.STATUS_ISSUED,
         PurchaseOrder.STATUS_PARTLY_RECEIVED),
    )


def _numbers(qs, field, limit=5):
    nums = [n or '(draft)' for n in qs.order_by(field).values_list(field, flat=True)[:limit + 1]]
    return ', '.join(nums[:limit]) + (', …' if len(nums) > limit else '')


def _plural(n, noun):
    return f'{n} open {noun}' + ('' if n == 1 else 's')


def _open_record_blockers(contacts):
    """Open jobs / invoices / POs attached to any of `contacts` (an iterable
    or queryset), as human sentences (spec §4.2 blockers 2–4)."""
    from apps.invoicing.models import Invoice
    from apps.jobs.models import Job
    from apps.purchasing.models import PurchaseOrder
    open_jobs, open_invoices, open_pos = _open_statuses()
    blockers = []
    jobs = Job.objects.filter(contact__in=contacts, status__in=open_jobs)
    if (n := jobs.count()):
        blockers.append(f'{_plural(n, "job")} ({_numbers(jobs, "job_number")})')
    invoices = Invoice.objects.filter(job__contact__in=contacts, status__in=open_invoices)
    if (n := invoices.count()):
        blockers.append(f'{_plural(n, "invoice")} ({_numbers(invoices, "invoice_number")})')
    pos = PurchaseOrder.objects.filter(contact__in=contacts, status__in=open_pos)
    if (n := pos.count()):
        blockers.append(f'{_plural(n, "PO")} ({_numbers(pos, "po_number")})')
    return blockers


def _vendor_po_blockers(business):
    from apps.purchasing.models import PurchaseOrder
    _, _, open_pos = _open_statuses()
    pos = PurchaseOrder.objects.filter(business=business, status__in=open_pos)
    n = pos.count()
    return [f'{_plural(n, "PO")} ({_numbers(pos, "po_number")})'] if n else []


# Sentinel for distinguishing "not passed" from None
_sentinel = object()


def _push_status_to_qbo(obj, active):
    """Spec 6.6 failure policy: no QBO id or no connection -> nothing to
    push. Otherwise QBO must accept; its error becomes the user's error and
    the caller never reaches the local flip. Runs outside the local
    transaction so a failed push's QBOSyncLog row survives."""
    from apps.qbo.services import (QBOCustomerSyncService, QBOService,
                                   QBOVendorSyncService)
    has_customer = bool(getattr(obj, 'qbo_customer_id', None))
    has_vendor = bool(getattr(obj, 'qbo_vendor_id', None))
    if not (has_customer or has_vendor):
        return
    if QBOService.get_active_connection() is None:
        return
    verb = 'reactivate' if active else 'deactivate'
    try:
        if has_customer:
            QBOCustomerSyncService.set_active(obj, active)
        if has_vendor:
            QBOVendorSyncService.set_active(obj, active)
    except Exception as e:  # QBO/network/token - surfaced verbatim
        raise ValidationError(f'QuickBooks refused to {verb} {obj}: {e}')


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
            if not business.is_active:
                raise ValidationError({'business_id': [f'{business.business_name} is inactive.']})

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
        ContactService.assert_active(contact)

        for field, value in kwargs.items():
            setattr(contact, field, value)

        if business_pk is not _sentinel:
            if business_pk is None:
                contact.business = None
            else:
                try:
                    new_business = Business.objects.get(pk=business_pk)
                except Business.DoesNotExist:
                    raise NotFoundError(f'Business {business_pk} not found')
                if not new_business.is_active:
                    raise ValidationError({'business_id': [f'{new_business.business_name} is inactive.']})
                contact.business = new_business

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
    def find_business_by_name(business_name):
        """Case-insensitive lookup for an existing business with this name,
        or None. Shared by the pre-create duplicate check below and by the
        API's check-name endpoint (used to warn before a contact is created
        for a business that's about to fail as a duplicate)."""
        name = (business_name or '').strip()
        if not name:
            return None
        return Business.objects.filter(business_name__iexact=name).first()

    @staticmethod
    def _check_duplicate_business_name(business_name):
        """Raise a rich ValidationError if a business with this name (case-
        insensitively) already exists, so the caller can identify *which*
        business conflicted and surface a "did you mean this one?" prompt
        instead of a bare validation error."""
        existing = ContactService.find_business_by_name(business_name)
        if existing:
            raise ValidationError(
                'A business with this name already exists.',
                code='duplicate_business_name',
                params={'business_id': existing.pk},
            )

    @staticmethod
    def create_business(contacts_data, **kwargs):
        """Create a business with one or more contacts.

        contacts_data: list of dicts with contact field values.
        First contact becomes the default_contact.
        """
        if not contacts_data:
            raise ValidationError('At least one contact is required.')

        ContactService._check_duplicate_business_name(kwargs.get('business_name'))

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

        ContactService._check_duplicate_business_name(kwargs.get('business_name'))

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
        ContactService.assert_active(business)
        if kwargs.get('default_contact') is not None:
            ContactService.assert_active(kwargs['default_contact'])

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
        ContactService.assert_active(business)
        ContactService.assert_active(contact)
        if contact.business != business:
            raise ValidationError(
                f'Contact "{contact}" is not associated with business '
                f'"{business.business_name}".'
            )
        business.default_contact = contact
        business.save(update_fields=['default_contact'])

    # --- Active / inactive (spec §4) ---

    @staticmethod
    def assert_active(obj):
        """Refuse any edit to an inactive record (spec §4.7)."""
        if not obj.is_active:
            raise ValidationError(f'{obj} is inactive. Reactivate it before editing.')

    @staticmethod
    def contact_deactivation_blockers(contact):
        blockers = []
        business = contact.business
        if (business is not None and business.is_active
                and business.default_contact_id == contact.pk):
            blockers.append(f'default contact for {business.business_name} '
                            f'(choose another default first)')
        blockers.extend(_open_record_blockers([contact]))
        return blockers

    @staticmethod
    def deactivate_contact(contact, *, push_to_qbo=True):
        if not contact.is_active:
            return contact
        blockers = ContactService.contact_deactivation_blockers(contact)
        if blockers:
            raise ValidationError(f'Cannot deactivate {contact}: ' + '; '.join(blockers) + '.')
        if push_to_qbo:
            _push_status_to_qbo(contact, False)
        with transaction.atomic():
            contact.is_active = False
            contact.save()
        return contact

    @staticmethod
    def reactivate_contact(contact, *, push_to_qbo=True):
        if contact.is_active:
            return contact
        business = contact.business
        if business is not None and not business.is_active:
            raise ValidationError(
                f'Cannot reactivate {contact}: business {business.business_name} is inactive. '
                f'Reactivate the business first.')
        if push_to_qbo:
            _push_status_to_qbo(contact, True)
        with transaction.atomic():
            contact.is_active = True
            contact.save()
        return contact

    @staticmethod
    def business_deactivation_blockers(business):
        return (_open_record_blockers(business.contacts.all())
                + _vendor_po_blockers(business))

    @staticmethod
    def deactivate_business_impact(business):
        contacts = list(business.contacts.all())
        return {
            'contact_count': len(contacts),
            'contact_names': [c.name for c in contacts],
            'blockers': ([] if not business.is_active
                         else ContactService.business_deactivation_blockers(business)),
        }

    @staticmethod
    def deactivate_business(business, *, push_to_qbo=True):
        if not business.is_active:
            return business
        blockers = ContactService.business_deactivation_blockers(business)
        if blockers:
            raise ValidationError(f'Cannot deactivate {business}: ' + '; '.join(blockers) + '.')
        if push_to_qbo:
            _push_status_to_qbo(business, False)
        with transaction.atomic():
            business.is_active = False
            business.save()
            for contact in list(business.contacts.all()):
                if contact.is_active:
                    contact.is_active = False
                    contact.save()
        return business

    @staticmethod
    def reactivate_business(business, *, push_to_qbo=True):
        if business.is_active:
            return business
        if push_to_qbo:
            _push_status_to_qbo(business, True)
        with transaction.atomic():
            business.is_active = True
            business.save()
            for contact in list(business.contacts.all()):
                if not contact.is_active:
                    contact.is_active = True
                    contact.save()
        return business

    @staticmethod
    def add_note(obj, object_type, text):
        ContactService.assert_active(obj)
        return record_history(entry_type='note', object_type=object_type,
                              object_id=obj.pk, text=text)

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
        ContactService.assert_active(obj)
        tag, _ = Tag.objects.get_or_create(name=name)
        obj.tags.add(tag)
        return obj.tags.all()

    @staticmethod
    def detach(obj, tag_id):
        ContactService.assert_active(obj)
        obj.tags.remove(tag_id)
        return obj.tags.all()
