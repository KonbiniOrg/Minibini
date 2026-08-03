"""
Service classes for core application functionality.
"""

from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
from imap_tools import MailBox, AND
from .models import Configuration, AppState, EmailRecord, TempEmail, AccountingCategory


def _attachments_metadata(msg):
    """Build the [{filename, content_type, size}, …] list cached on TempEmail
    from an imap_tools message. Skips payloads — those are re-fetched by the
    download endpoint when needed."""
    return [
        {
            'filename': att.filename,
            'content_type': att.content_type,
            'size': len(att.payload),
        }
        for att in (msg.attachments or [])
    ]


def _aware(dt):
    """Coerce a possibly-naive datetime to tz-aware (assumes UTC).

    IMAP message dates are usually aware (parsed from the Date header's
    offset) but come back naive when the header is missing/malformed, and the
    persisted fetch cursor can round-trip naive — comparing the two raises."""
    if dt is not None and timezone.is_naive(dt):
        return timezone.make_aware(dt, dt_timezone.utc)
    return dt


def _header_value(msg, name):
    """Pull a single header value from an imap_tools message; '' if missing.
    Headers are stored as list-of-strings per name; we take the first item."""
    raw = msg.headers.get(name, ())
    if not raw:
        return ''
    value = raw[0] if isinstance(raw, (list, tuple)) else raw
    return (value or '').strip()


class ServiceError(Exception):
    """Base exception for service-layer errors."""
    pass


class NotFoundError(ServiceError):
    """Raised when a requested object does not exist."""
    pass


class NumberGenerationService:
    """
    Service for generating sequential document numbers using Configuration key-value pairs.

    Supports patterns like:
    - "JOB-{year}-{counter:04d}" -> JOB-2025-0001
    - "INV-{year}-{month:02d}-{counter:05d}" -> INV-2025-10-00001

    Thread-safe using database-level locking. Numbers are assigned atomically
    when generate_next_number() is called.

    Configuration keys:
    - job_number_sequence: Pattern for job numbers
    - job_counter: Current counter for jobs
    - invoice_number_sequence: Pattern for invoice numbers
    - invoice_counter: Current counter for invoices
    - po_number_sequence: Pattern for PO numbers
    - po_counter: Current counter for POs

    Estimates are not numbered here: an estimate's number is its job's
    job_number, with the version distinguishing revisions.
    """

    # Map document types to their key names. The *pattern* (sequence) is a
    # user-settable Configuration key; the *counter* is machine state in AppState.
    # (No 'estimate' entry: estimates derive their number as {job}-{ver}, not via
    # this service.)
    SEQUENCE_KEYS = {
        'job': 'job_number_sequence',
        'invoice': 'invoice_number_sequence',
        'po': 'po_number_sequence',
    }

    COUNTER_KEYS = {
        'job': 'job_counter',
        'invoice': 'invoice_counter',
        'po': 'po_counter',
    }

    # Per-document-type model and number-field used for collision detection.
    # The service advances the counter past any pre-existing row that already
    # uses the candidate number — this lets a fresh data load with a reset
    # counter still produce unique numbers.
    NUMBER_OWNERS = {
        'job': ('apps.jobs.models', 'Job', 'job_number'),
        'invoice': ('apps.invoicing.models', 'Invoice', 'invoice_number'),
        'po': ('apps.purchasing.models', 'PurchaseOrder', 'po_number'),
    }

    MAX_COLLISION_ATTEMPTS = 1000

    @classmethod
    def _model_for(cls, document_type: str):
        import importlib
        module_path, model_name, field_name = cls.NUMBER_OWNERS[document_type]
        module = importlib.import_module(module_path)
        return getattr(module, model_name), field_name

    @classmethod
    def generate_next_number(cls, document_type: str) -> str:
        """
        Generate the next sequential number for the given document type.

        Args:
            document_type: One of 'job', 'invoice', 'po'

        Returns:
            The next formatted document number

        Raises:
            ValidationError: If document_type is invalid or configuration is missing
        """
        if document_type not in cls.SEQUENCE_KEYS:
            raise ValidationError(
                f"Invalid document_type '{document_type}'. "
                f"Must be one of: {', '.join(cls.SEQUENCE_KEYS.keys())}"
            )

        sequence_key = cls.SEQUENCE_KEYS[document_type]
        counter_key = cls.COUNTER_KEYS[document_type]

        with transaction.atomic():
            # Get the pattern
            try:
                pattern_config = Configuration.objects.get(key=sequence_key)
                pattern = pattern_config.value
            except Configuration.DoesNotExist:
                raise ValidationError(
                    f"Configuration key '{sequence_key}' not found. "
                    "Please create it in the admin interface."
                )

            if not pattern:
                raise ValidationError(
                    f"No sequence pattern configured for {document_type}. "
                    f"Please set value for key '{sequence_key}'."
                )

            # Lock and increment the counter (machine state — lives in AppState)
            try:
                counter_state = AppState.objects.select_for_update().get(key=counter_key)
                current_counter = int(counter_state.value or '0')
            except AppState.DoesNotExist:
                raise ValidationError(
                    f"AppState key '{counter_key}' not found. "
                    "It is seeded by migration/fixtures."
                )

            # Walk forward until we find a counter value that doesn't collide
            # with an existing row. Self-heals after data reloads that reset
            # the counter while keeping existing rows.
            Model, field_name = cls._model_for(document_type)
            next_counter = current_counter + 1
            for _ in range(cls.MAX_COLLISION_ATTEMPTS):
                candidate = cls._format_number(pattern, next_counter)
                if not Model.objects.filter(**{field_name: candidate}).exists():
                    break
                next_counter += 1
            else:
                raise ValidationError(
                    f"Could not find an unused {document_type} number after "
                    f"{cls.MAX_COLLISION_ATTEMPTS} attempts."
                )

            counter_state.value = str(next_counter)
            counter_state.save()

            return candidate

    @classmethod
    def _format_number(cls, pattern: str, counter: int) -> str:
        """
        Format a number using the pattern template.

        Supports placeholders:
        - {year} - 4-digit year
        - {month:02d} - 2-digit month with leading zero
        - {day:02d} - 2-digit day with leading zero
        - {counter:04d} - counter with specified formatting (e.g., 0001)
        - {counter} - counter with no formatting

        Args:
            pattern: The pattern template string
            counter: The counter value to use

        Returns:
            The formatted number string
        """
        now = datetime.now()

        # Build a context dict with available variables
        context = {
            'year': now.year,
            'month': now.month,
            'day': now.day,
            'counter': counter,
        }

        # Format the string using the pattern
        try:
            formatted = pattern.format(**context)
        except (KeyError, ValueError) as e:
            # If pattern is invalid, return a safe fallback
            formatted = f"{counter:04d}"

        return formatted



class EmailService:
    """
    Service class for managing email integration via IMAP.
    Handles fetching emails, storing metadata, and retrieving full content on-demand.

    Configuration keys used:
    - email_retention_days: Number of days to retain temporary email data (default: 90)
    - latest_email_date: Most recent email date fetched from IMAP server (ISO format)
    - email_display_limit: Number of emails to display in inbox (default: 30)
    """

    def __init__(self):
        """Initialize with IMAP configuration: Configuration rows first
        (Settings → Email), env settings fallback."""
        from apps.core.email_account import email_account
        account = email_account()
        self.imap_server = account['imap_server'] or None
        self.email = account['address'] or None
        self.password = account['password'] or None
        self.mailbox_folder = getattr(settings, 'EMAIL_IMAP_FOLDER', 'INBOX')

    def fetch_new_emails(self, mark_as_seen=False):
        """
        Fetch new emails from IMAP server and store metadata.

        Args:
            mark_as_seen (bool): Whether to mark fetched emails as seen on server

        Returns:
            dict: Statistics about emails fetched (new, existing, errors)
        """
        if not self._validate_config():
            raise ValueError("Email configuration incomplete. Check settings for IMAP server, user, and password.")

        stats = {'new': 0, 'existing': 0, 'errors': []}

        try:
            with MailBox(self.imap_server).login(self.email, self.password) as mailbox:
                mailbox.folder.set(self.mailbox_folder)

                # Fetch unseen emails
                for msg in mailbox.fetch(AND(seen=False)):
                    try:
                        # Get Message-ID from headers
                        message_id = msg.headers.get('message-id', [f'<{msg.uid}@unknown>'])[0]

                        # Check if we already have this email
                        if EmailRecord.objects.filter(message_id=message_id).exists():
                            stats['existing'] += 1
                            continue

                        # Create permanent EmailRecord
                        email_record = EmailRecord.objects.create(
                            message_id=message_id,
                            job=None,  # No automatic job linking per user request
                        )

                        # Create temporary metadata cache
                        TempEmail.objects.create(
                            email_record=email_record,
                            uid=msg.uid,
                            subject=msg.subject or '',
                            from_email=msg.from_ or 'unknown@example.com',
                            to_email=', '.join(msg.to) if msg.to else '',
                            cc_email=', '.join(msg.cc) if msg.cc else '',
                            date_sent=_aware(msg.date),
                            has_attachments=bool(msg.attachments),
                            text_body=getattr(msg, 'text', '') or '',
                            html_body=getattr(msg, 'html', '') or '',
                            attachments_metadata=_attachments_metadata(msg),
                            in_reply_to=_header_value(msg, 'in-reply-to'),
                            references=_header_value(msg, 'references'),
                        )

                        # Auto-link to a parent's associations if In-Reply-To
                        # or References points at one of our outbound rows.
                        email_record.refresh_from_db()
                        EmailService.correlate_reply(email_record)

                        stats['new'] += 1

                    except Exception as e:
                        # Use UID in error message if message_id not available
                        msg_identifier = msg.headers.get('message-id', [f'UID:{msg.uid}'])[0]
                        stats['errors'].append(f"Error processing {msg_identifier}: {str(e)}")

        except Exception as e:
            stats['errors'].append(f"IMAP connection error: {str(e)}")

        return stats

    def get_email_content(self, email_record_id):
        """
        Fetch full email content from IMAP server on-demand.

        Args:
            email_record_id: Primary key of EmailRecord

        Returns:
            dict: Email content including text, html, and attachments, or None if not found
        """
        if not self._validate_config():
            raise ValueError("Email configuration incomplete.")

        try:
            email_record = EmailRecord.objects.select_related('temp_data').get(
                email_record_id=email_record_id
            )
        except EmailRecord.DoesNotExist:
            return None

        # Check if we have temp data with UID
        if not hasattr(email_record, 'temp_data'):
            # No temp data - try to fetch by message_id
            return self._fetch_by_message_id(email_record.message_id)

        temp = email_record.temp_data

        # Prefer cached body + attachment metadata when both are available.
        # Pre-backfill rows with has_attachments=True but an empty
        # attachments_metadata still fall back to IMAP so the detail view
        # can show what's attached. Payloads are never cached — those come
        # from the future per-attachment download endpoint.
        body_cached = bool(temp.text_body or temp.html_body)
        attachments_cached = (
            not temp.has_attachments or bool(temp.attachments_metadata)
        )
        if body_cached and attachments_cached:
            return {
                'subject': temp.subject,
                'from': temp.from_email,
                'to': [a.strip() for a in temp.to_email.split(',') if a.strip()],
                'cc': [a.strip() for a in temp.cc_email.split(',') if a.strip()],
                'date': temp.date_sent,
                'text': temp.text_body,
                'html': temp.html_body,
                'attachments': list(temp.attachments_metadata or []),
            }

        uid = temp.uid

        try:
            with MailBox(self.imap_server).login(self.email, self.password) as mailbox:
                mailbox.folder.set(self.mailbox_folder)

                # Fetch by UID
                for msg in mailbox.fetch(AND(uid=uid)):
                    return {
                        'subject': msg.subject,
                        'from': msg.from_,
                        'to': msg.to,
                        'cc': msg.cc,
                        'date': msg.date,
                        'text': msg.text,
                        'html': msg.html,
                        'attachments': [
                            {
                                'filename': att.filename,
                                'content_type': att.content_type,
                                'size': len(att.payload),
                            }
                            for att in msg.attachments
                        ],
                    }

        except Exception as e:
            # If UID fetch fails, try by message_id
            return self._fetch_by_message_id(email_record.message_id)

        return None

    def _fetch_by_message_id(self, message_id):
        """
        Fallback method to fetch email by Message-ID header.
        Used when UID is not available or has changed.
        """
        if not self._validate_config():
            return None

        try:
            with MailBox(self.imap_server).login(self.email, self.password) as mailbox:
                mailbox.folder.set(self.mailbox_folder)

                # Search by Message-ID header
                for msg in mailbox.fetch(AND(header=['Message-ID', message_id])):
                    return {
                        'subject': msg.subject,
                        'from': msg.from_,
                        'to': msg.to,
                        'cc': msg.cc,
                        'date': msg.date,
                        'text': msg.text,
                        'html': msg.html,
                        'attachments': [
                            {
                                'filename': att.filename,
                                'content_type': att.content_type,
                                'size': len(att.payload),
                            }
                            for att in msg.attachments
                        ],
                    }

        except Exception:
            pass

        return None

    def fetch_emails_by_date_range(self, days_back=30):
        """
        Fetch emails from IMAP server since latest_email_date or last N days.
        Updates latest_email_date after fetching.

        Args:
            days_back (int): Number of days back to use if latest_email_date not set

        Returns:
            dict: Statistics about emails fetched (new, existing, errors, latest_date)
        """
        if not self._validate_config():
            raise ValueError("Email configuration incomplete. Check settings for IMAP server, user, and password.")

        stats = {'new': 0, 'existing': 0, 'errors': [], 'latest_date': None}

        try:
            # Get or create the latest_email_date fetch cursor (machine state)
            try:
                latest_date_state = AppState.objects.get(key='latest_email_date')
                date_threshold = _aware(
                    datetime.fromisoformat(latest_date_state.value))
            except AppState.DoesNotExist:
                # Create default cursor
                date_threshold = timezone.now() - timedelta(days=days_back)
                AppState.objects.create(
                    key='latest_email_date',
                    value=date_threshold.isoformat()
                )
            except (ValueError, AttributeError):
                # Invalid date format, reset to default
                date_threshold = timezone.now() - timedelta(days=days_back)

            # Ensure we have email_retention_days config
            try:
                Configuration.objects.get(key='email_retention_days')
            except Configuration.DoesNotExist:
                Configuration.objects.create(key='email_retention_days', value='90')

            # Ensure we have email_display_limit config
            try:
                Configuration.objects.get(key='email_display_limit')
            except Configuration.DoesNotExist:
                Configuration.objects.create(key='email_display_limit', value='30')

            most_recent_email_date = date_threshold

            with MailBox(self.imap_server).login(self.email, self.password) as mailbox:
                mailbox.folder.set(self.mailbox_folder)

                # Fetch emails since date_threshold
                for msg in mailbox.fetch(AND(date_gte=date_threshold.date())):
                    try:
                        # Get Message-ID from headers
                        message_id = msg.headers.get('message-id', [f'<{msg.uid}@unknown>'])[0]

                        # Track most recent email date (msg.date is naive when
                        # the Date header is missing/malformed)
                        msg_date = _aware(msg.date)
                        if msg_date and msg_date > most_recent_email_date:
                            most_recent_email_date = msg_date

                        # Check if we already have this email
                        if EmailRecord.objects.filter(message_id=message_id).exists():
                            stats['existing'] += 1
                            continue

                        # Create permanent EmailRecord
                        email_record = EmailRecord.objects.create(
                            message_id=message_id,
                            job=None,  # No automatic job linking per user request
                        )

                        # Create temporary metadata cache
                        TempEmail.objects.create(
                            email_record=email_record,
                            uid=msg.uid,
                            subject=msg.subject or '',
                            from_email=msg.from_ or 'unknown@example.com',
                            to_email=', '.join(msg.to) if msg.to else '',
                            cc_email=', '.join(msg.cc) if msg.cc else '',
                            date_sent=_aware(msg.date),
                            has_attachments=bool(msg.attachments),
                            text_body=getattr(msg, 'text', '') or '',
                            html_body=getattr(msg, 'html', '') or '',
                            attachments_metadata=_attachments_metadata(msg),
                            in_reply_to=_header_value(msg, 'in-reply-to'),
                            references=_header_value(msg, 'references'),
                        )

                        # Auto-link to a parent's associations if In-Reply-To
                        # or References points at one of our outbound rows.
                        email_record.refresh_from_db()
                        EmailService.correlate_reply(email_record)

                        stats['new'] += 1

                    except Exception as e:
                        # Use UID in error message if message_id not available
                        msg_identifier = msg.headers.get('message-id', [f'UID:{msg.uid}'])[0]
                        stats['errors'].append(f"Error processing {msg_identifier}: {str(e)}")

            # Update latest_email_date to most recent email found
            if most_recent_email_date > date_threshold:
                latest_date_state = AppState.objects.get(key='latest_email_date')
                latest_date_state.value = most_recent_email_date.isoformat()
                latest_date_state.save()
                stats['latest_date'] = most_recent_email_date

        except Exception as e:
            stats['errors'].append(f"IMAP connection error: {str(e)}")

        return stats

    def cleanup_old_temp_emails(self, retention_days=None):
        """Delete TempEmail rows whose retention clock has elapsed.

        Retention clock semantics (the "tweak"):

        - An unlinked TempEmail (its EmailRecord has no ``job`` /
          ``purchase_order``) uses ``TempEmail.created_at`` as the
          clock start — original behavior.
        - A linked TempEmail uses the *finality date* of its linked objects
          instead: the most recent ``HistoryEntry`` recording a transition into
          a final status, per linked object. The TempEmail is eligible only if
          **every** linked object is currently in a final status AND every
          object's finality timestamp is older than the cutoff. A still-active
          link keeps the email indefinitely.
        - If a linked object is in a final status but no qualifying
          HistoryEntry exists (pre-history-tracking data, or created directly
          in a final state), fall back to ``TempEmail.created_at`` so emails
          aren't stuck unpurgeable.

        EmailRecord rows are preserved permanently regardless.
        """
        from django.db.models import Max
        from apps.core.history import history_model_for
        from apps.jobs.models import Job
        from apps.purchasing.models import PurchaseOrder

        if retention_days is None:
            try:
                config = Configuration.objects.get(key='email_retention_days')
                retention_days = int(config.value)
            except (Configuration.DoesNotExist, ValueError):
                retention_days = 90

        cutoff = timezone.now() - timedelta(days=retention_days)

        FINAL_STATUSES = {
            'job': (
                Job,
                'job_id',
                {Job.STATUS_COMPLETED, Job.STATUS_REJECTED, Job.STATUS_CANCELLED},
            ),
            'purchaseorder': (
                PurchaseOrder,
                'purchase_order_id',
                {PurchaseOrder.STATUS_RECEIVED_IN_FULL, PurchaseOrder.STATUS_CANCELLED},
            ),
        }

        # Per-type lookup: {linked_pk: finality_timestamp_or_None}.
        # None means "currently final but no qualifying HistoryEntry" → caller
        # falls back to TempEmail.created_at for that link.
        finality_by_type = {}
        for object_type, (model, _fk, final_set) in FINAL_STATUSES.items():
            final_ids = list(
                model.objects.filter(status__in=final_set).values_list('pk', flat=True)
            )
            finality_map = dict.fromkeys(final_ids, None)
            if final_ids:
                rows = (
                    history_model_for(object_type).objects
                    .filter(
                        object_type=object_type,
                        object_id__in=final_ids,
                        changes__status__new__in=list(final_set),
                    )
                    .values('object_id')
                    .annotate(last_final=Max('timestamp'))
                )
                for row in rows:
                    finality_map[row['object_id']] = row['last_final']
            finality_by_type[object_type] = finality_map

        # Walk every TempEmail. The table is small in this app's lifetime;
        # if it grows we can switch to batched queries later.
        eligible_ids = []
        candidates = TempEmail.objects.select_related('email_record').only(
            'temp_email_id', 'created_at',
            'email_record__job_id',
            'email_record__purchase_order_id',
        )
        for temp in candidates:
            er = temp.email_record
            links = []
            if er.job_id:
                links.append(('job', er.job_id))
            if er.purchase_order_id:
                links.append(('purchaseorder', er.purchase_order_id))

            if not links:
                if temp.created_at < cutoff:
                    eligible_ids.append(temp.temp_email_id)
                continue

            # Linked. Strictest rule: every link must be purgeable.
            all_purgeable = True
            for object_type, linked_pk in links:
                finality_map = finality_by_type[object_type]
                if linked_pk not in finality_map:
                    # Linked object is NOT currently in a final status.
                    all_purgeable = False
                    break
                last_final = finality_map[linked_pk]
                if last_final is None:
                    # Final but no HistoryEntry — fall back to email date.
                    if temp.created_at >= cutoff:
                        all_purgeable = False
                        break
                elif last_final >= cutoff:
                    all_purgeable = False
                    break

            if all_purgeable:
                eligible_ids.append(temp.temp_email_id)

        if not eligible_ids:
            return 0
        deleted_count, _ = TempEmail.objects.filter(
            temp_email_id__in=eligible_ids
        ).delete()
        return deleted_count

    def _validate_config(self):
        """Check if required IMAP configuration is present."""
        return all([self.imap_server, self.email, self.password])

    # Allowlist of EmailRecord fields that the association helpers will
    # touch, plus the lazy-imported model the FK points at. New target?
    # Add it here.
    _ASSOC_TARGETS = {
        'job': ('apps.jobs.models', 'Job'),
        'purchase_order': ('apps.purchasing.models', 'PurchaseOrder'),
    }

    @staticmethod
    def _resolve_target_model(target_field):
        try:
            module_path, class_name = EmailService._ASSOC_TARGETS[target_field]
        except KeyError:
            raise ValueError(
                f'Unknown EmailRecord association field: {target_field!r}. '
                f'Expected one of {sorted(EmailService._ASSOC_TARGETS)}.'
            )
        import importlib
        return getattr(importlib.import_module(module_path), class_name)

    @staticmethod
    def associate_with(email_record_id, target_field, target_pk):
        """Set ``EmailRecord.<target_field>`` to the row identified by
        ``target_pk``.

        Args:
            email_record_id: PK of EmailRecord
            target_field: one of 'job', 'purchase_order'
            target_pk: PK of the target row

        Returns:
            EmailRecord with the target FK set

        Raises:
            ValueError: target_field not in the allowlist
            NotFoundError: email_record or target row missing
        """
        target_model = EmailService._resolve_target_model(target_field)
        try:
            email_record = EmailRecord.objects.get(pk=email_record_id)
        except EmailRecord.DoesNotExist:
            raise NotFoundError(f'EmailRecord {email_record_id} not found')
        try:
            target = target_model.objects.get(pk=target_pk)
        except target_model.DoesNotExist:
            raise NotFoundError(
                f'{target_model.__name__} {target_pk} not found'
            )
        setattr(email_record, target_field, target)
        email_record.save()
        EmailService.propagate_thread_association(email_record, target_field)
        return email_record

    @staticmethod
    def propagate_thread_association(email_record, target_field):
        """Copy ``email_record.<target_field>`` to other EmailRecords in the
        same RFC 5322 thread that have a NULL value for the same field.

        No-op when email_record's own value is null (nothing to propagate)
        or when target_field isn't in the allowlist. Does NOT overwrite a
        non-null value on a sibling — that's a deliberate human choice the
        propagation respects.

        Uses bulk ``.update()`` — no per-row history entries. The user-
        initiated event on the source email IS the audited action; the
        propagated set is the implicit consequence the design promises.
        """
        if target_field not in EmailService._ASSOC_TARGETS:
            return
        source_value = getattr(email_record, f'{target_field}_id', None)
        if source_value is None:
            return
        from apps.core.email_utils import collect_thread_member_ids
        thread_pks = collect_thread_member_ids(email_record)
        if not thread_pks:
            return
        EmailRecord.objects.filter(
            pk__in=thread_pks,
            **{f'{target_field}_id__isnull': True},
        ).update(**{f'{target_field}_id': source_value})

    @staticmethod
    def disassociate_from(email_record_id, target_field):
        """Clear ``EmailRecord.<target_field>``.

        Args:
            email_record_id: PK of EmailRecord
            target_field: one of 'job', 'purchase_order'

        Returns:
            EmailRecord with the target FK cleared

        Raises:
            ValueError: target_field not in the allowlist
            NotFoundError: email_record missing
        """
        # Validate field name early.
        EmailService._resolve_target_model(target_field)
        try:
            email_record = EmailRecord.objects.get(pk=email_record_id)
        except EmailRecord.DoesNotExist:
            raise NotFoundError(f'EmailRecord {email_record_id} not found')
        setattr(email_record, target_field, None)
        email_record.save()
        return email_record

    @staticmethod
    def associate_with_job(email_record_id, job_id):
        """Backwards-compatible shim — delegates to associate_with."""
        return EmailService.associate_with(email_record_id, 'job', job_id)

    @staticmethod
    def disassociate_from_job(email_record_id):
        """Backwards-compatible shim — delegates to disassociate_from."""
        return EmailService.disassociate_from(email_record_id, 'job')

    @staticmethod
    def correlate_reply(email_record):
        """Auto-link an inbound EmailRecord to its parent's associations,
        when In-Reply-To or References points at one of our existing
        EmailRecord.message_id values.

        Walks In-Reply-To first (the immediate parent — wins on conflict),
        then the References chain right-to-left (most recent first). The
        first match's job / purchase_order FKs are copied onto
        `email_record` (any that are non-null on the parent).

        Args:
            email_record: the newly-fetched inbound EmailRecord. Must have a
                ``temp_data`` row whose `in_reply_to` / `references` headers
                were populated at fetch time.

        No-op if no parent is found, or if the email_record has no temp_data.
        """
        temp = getattr(email_record, 'temp_data', None)
        if not temp:
            return

        candidates = []
        if temp.in_reply_to:
            candidates.append(temp.in_reply_to.strip())
        if temp.references:
            # References is a space-separated chain; walk right-to-left so the
            # most recent parent wins among References-only matches.
            tokens = [t.strip() for t in temp.references.split() if t.strip()]
            candidates.extend(reversed(tokens))

        for token in candidates:
            # Some clients add stray whitespace inside the brackets.
            parent_id = token.strip()
            try:
                parent = EmailRecord.objects.get(message_id=parent_id)
            except EmailRecord.DoesNotExist:
                continue
            # Copy non-null associations from the parent. Don't overwrite
            # whatever might already be set on the reply (rare, but possible
            # if someone manually pre-associated before the correlation pass).
            updates = {}
            for field in ('job_id', 'purchase_order_id'):
                parent_value = getattr(parent, field)
                if parent_value and not getattr(email_record, field):
                    updates[field] = parent_value
            if updates:
                EmailRecord.objects.filter(pk=email_record.pk).update(**updates)
                for field, value in updates.items():
                    setattr(email_record, field, value)
                # Propagate each just-set FK to the rest of the thread —
                # closes the gap where an earlier sibling was orphaned
                # before this inbound's correlation linked the new arrival.
                for field in updates:
                    target_field = field.removesuffix('_id')
                    EmailService.propagate_thread_association(email_record, target_field)
                return  # Stop at the first parent that contributed something.
            # Otherwise keep walking: the immediate parent had no FKs to
            # copy; try the next candidate up the References chain. This
            # is what lets a new reply inherit context from a grandparent
            # when the immediate parent is itself orphaned.


class ReorderService:
    """Low-level service for reordering items within a container by swapping sort_order."""

    @staticmethod
    def reorder_container_items(items_qs, item_type, item_id, direction):
        """Move an item up or down in sort_order among its peers.

        items_qs: queryset of items in a single container (ordered arbitrarily)
        item_type: string identifier used by callers (currently always 'task')
        item_id: pk of the item to move
        direction: 'up' or 'down'
        """
        items = list(items_qs.order_by('sort_order', 'pk'))

        current_index = None
        for i, obj in enumerate(items):
            if obj.pk == item_id:
                current_index = i
                break

        if current_index is None:
            raise ValidationError('Item not found in container.')

        if direction == 'up' and current_index > 0:
            swap_index = current_index - 1
        elif direction == 'down' and current_index < len(items) - 1:
            swap_index = current_index + 1
        else:
            raise ValidationError(f'Cannot move item {direction} from current position.')

        current_obj = items[current_index]
        swap_obj = items[swap_index]
        current_obj.sort_order, swap_obj.sort_order = swap_obj.sort_order, current_obj.sort_order
        current_obj.save()
        swap_obj.save()


# Backward-compat alias for callers that still import BundlingService
BundlingService = ReorderService


class LineItemService:
    """
    Service for managing line items across different container types.

    Works with any container object (Estimate, Invoice, PurchaseOrder)
    that has line items inheriting from BaseLineItem.

    Status validation is the responsibility of calling domain services
    (e.g. EstimateService, PurchaseOrderService), not LineItemService.
    Status validation is delegated to callers, not enforced here.
    """

    @staticmethod
    def normalize_fk_kwargs(model_class, kwargs):
        """Convert FK fields passed as PKs to _id fields for model constructor.

        Allows services to accept either model instances or integer PKs
        for foreign key fields (e.g., inventory_item=5 becomes
        inventory_item_id=5).
        """
        cleaned = {}
        fk_fields = {
            f.name for f in model_class._meta.get_fields()
            if f.many_to_one or f.one_to_one
        }
        for key, value in kwargs.items():
            if key in fk_fields and value is not None and not hasattr(value, 'pk'):
                cleaned[f'{key}_id'] = value
            else:
                cleaned[key] = value
        return cleaned

    @classmethod
    def get_line_item_model(cls, line_item):
        """
        Get the model class for a line item instance.

        Args:
            line_item: An instance of a BaseLineItem subclass

        Returns:
            The model class
        """
        return line_item.__class__

    @classmethod
    def get_parent_container(cls, line_item):
        """
        Get the parent container object for a line item.

        Args:
            line_item: An instance of a BaseLineItem subclass

        Returns:
            The parent container object (Estimate, Invoice, etc.)
        """
        parent_field_name = line_item.get_parent_field_name()
        return getattr(line_item, parent_field_name)

    @classmethod
    def save_line_item(cls, line_item):
        """Single write path for a line item: save it, then recompute any
        percentage-adjustment lines on its parent document. Use this instead of
        calling line_item.save() directly so adjustments never go stale."""
        from apps.core.adjustments import recompute_adjustments
        line_item.save()
        container = cls.get_parent_container(line_item)
        recompute_adjustments(cls.get_line_items_for_container(container, type(line_item)))
        return line_item

    @classmethod
    @transaction.atomic
    def delete_line_item_with_renumber(cls, line_item):
        """
        Delete a line item and renumber remaining items in the container.
        Also recomputes any percentage-adjustment lines after deletion.

        Callers must validate container status before calling this method.

        Args:
            line_item: An instance of a BaseLineItem subclass

        Returns:
            tuple: (parent_container, deleted_line_number)
        """
        from apps.core.adjustments import recompute_adjustments

        # Get parent container and model BEFORE deletion
        parent_container = cls.get_parent_container(line_item)
        line_item_model = cls.get_line_item_model(line_item)

        # Store info before deletion
        deleted_line_number = line_item.line_number
        parent_field_name = line_item.get_parent_field_name()

        # Delete the line item
        line_item.delete()

        # Renumber remaining line items
        remaining_items = line_item_model.objects.filter(
            **{parent_field_name: parent_container}
        ).order_by('line_number', 'line_item_id')

        # Reassign line numbers sequentially
        for index, item in enumerate(remaining_items, start=1):
            if item.line_number != index:
                item.line_number = index
                item.save()

        # Recompute adjustments after deletion and renumber
        recompute_adjustments(cls.get_line_items_for_container(parent_container, line_item_model))

        return parent_container, deleted_line_number

    @classmethod
    @transaction.atomic
    def reorder_line_item(cls, line_item, direction):
        """
        Reorder a line item within its container by swapping line numbers.

        Callers must validate container status before calling this method.

        Args:
            line_item: An instance of a BaseLineItem subclass
            direction: 'up' or 'down'

        Raises:
            ValidationError: If direction is invalid or item can't move

        Returns:
            The parent container object
        """
        # Get parent container
        parent_container = cls.get_parent_container(line_item)

        # Get all line items for this container
        line_item_model = cls.get_line_item_model(line_item)
        parent_field_name = line_item.get_parent_field_name()

        all_items = list(line_item_model.objects.filter(
            **{parent_field_name: parent_container}
        ).order_by('line_number', 'line_item_id'))

        # Find the index of the current line item
        try:
            current_index = next(
                i for i, item in enumerate(all_items)
                if item.line_item_id == line_item.line_item_id
            )
        except StopIteration:
            raise ValidationError('Line item not found in container.')

        # Determine the swap target
        if direction == 'up' and current_index > 0:
            swap_index = current_index - 1
        elif direction == 'down' and current_index < len(all_items) - 1:
            swap_index = current_index + 1
        else:
            raise ValidationError(f'Cannot move line item {direction} from current position.')

        # Swap line numbers
        current_item = all_items[current_index]
        swap_item = all_items[swap_index]
        current_item.line_number, swap_item.line_number = (
            swap_item.line_number,
            current_item.line_number
        )

        current_item.save()
        swap_item.save()

        return parent_container

    @classmethod
    def get_line_items_for_container(cls, container, line_item_model):
        """
        Get all line items for a container, ordered by line number.

        Args:
            container: The parent container object
            line_item_model: The LineItem model class

        Returns:
            QuerySet of line items ordered by line_number

        Raises:
            ValueError: If container type is not recognized
        """
        container_type = container.__class__.__name__

        # Map container types to field names
        field_name_map = {
            'Estimate': 'estimate',
            'Invoice': 'invoice',
            'PurchaseOrder': 'purchase_order',
        }

        parent_field_name = field_name_map.get(container_type)
        if not parent_field_name:
            raise ValueError(f'Unknown container type: {container_type}')

        return line_item_model.objects.filter(
            **{parent_field_name: container}
        ).order_by('line_number', 'line_item_id')

    @classmethod
    def calculate_total(cls, line_items):
        """
        Calculate the total amount for a collection of line items.

        Args:
            line_items: QuerySet or list of line items

        Returns:
            Decimal: Total amount
        """
        return sum(item.total_amount for item in line_items)


# NOTE: tax *amounts* are computed by QuickBooks, not the app. Per-line
# taxability is the line's accounting_category.taxable flag, read directly
# by the QBO invoice push (TaxCodeRef); QBO applies the rate.


class ConfigurationService:
    """Service for managing configuration: key-value settings and line item types."""

    # Fields frozen once an AccountingCategory is referenced anywhere.
    FROZEN_WHEN_REFERENCED = ('taxable', 'is_deposit')

    @staticmethod
    def set(key, value):
        """Set a Configuration key/value from the settings API — the views
        translate HTTP, this persists."""
        from .models import Configuration
        config, _ = Configuration.objects.update_or_create(
            key=key, defaults={'value': value})
        return config

    @staticmethod
    def create_accounting_category(**kwargs):
        """Create a new AccountingCategory from field values."""
        cat = AccountingCategory(**kwargs)
        cat.full_clean()
        cat.save()
        return cat

    @staticmethod
    def update_accounting_category(pk, **kwargs):
        """Update an existing AccountingCategory by PK.

        Raises:
            NotFoundError: if AccountingCategory not found
        """
        try:
            cat = AccountingCategory.objects.get(pk=pk)
        except AccountingCategory.DoesNotExist:
            raise NotFoundError(f'AccountingCategory {pk} not found')
        frozen = [
            f for f in ConfigurationService.FROZEN_WHEN_REFERENCED
            if f in kwargs and kwargs[f] != getattr(cat, f)
        ]
        if frozen and cat.is_referenced():
            raise ValidationError(
                f"{' and '.join(frozen)} cannot change on a category that is "
                'in use. Retire this category and create a replacement instead.'
            )
        for field, value in kwargs.items():
            setattr(cat, field, value)
        cat.full_clean()
        cat.save()
        return cat

    ACCOUNTING_CATEGORY_REFERENCED_MESSAGE = (
        'Accounting category is in use (materials, services, or '
        'line items reference it) and cannot be deleted.'
    )

    @staticmethod
    def delete_accounting_category(pk):
        """Delete an AccountingCategory. Most references PROTECT at the FK
        level; the adjustment_target_categories M2Ms (EstimateLineItem,
        InvoiceLineItem) don't, so is_referenced() (the same predicate that
        freezes edits) is checked up front. The ProtectedError catch stays
        as a backstop against any reference is_referenced() doesn't cover."""
        from django.db.models.deletion import ProtectedError
        try:
            cat = AccountingCategory.objects.get(pk=pk)
        except AccountingCategory.DoesNotExist:
            raise NotFoundError(f'AccountingCategory {pk} not found')
        if cat.is_referenced():
            raise ValidationError(
                ConfigurationService.ACCOUNTING_CATEGORY_REFERENCED_MESSAGE,
                code='referenced')
        try:
            cat.delete()
        except ProtectedError:
            raise ValidationError(
                ConfigurationService.ACCOUNTING_CATEGORY_REFERENCED_MESSAGE,
                code='referenced')

    # -- RateScheme (config-page CRUD; the referenced-freeze decision lives
    #    here, the viewset only shapes the 409 payload) --------------------

    @staticmethod
    def create_rate_scheme(**fields):
        from apps.jobs.models import RateScheme
        scheme = RateScheme(**fields)
        scheme.full_clean()
        scheme.save()
        return scheme

    @staticmethod
    def update_rate_scheme(scheme, **fields):
        """Update an unreferenced scheme. Referenced schemes are frozen —
        every edit path is refused; new pricing means a new version
        (supersede)."""
        if scheme.is_referenced():
            raise ValidationError(
                'Scheme is referenced; create a new version instead of '
                'editing.', code='referenced')
        for field, value in fields.items():
            setattr(scheme, field, value)
        scheme.full_clean()
        scheme.save()
        return scheme

    @staticmethod
    def delete_rate_scheme(scheme):
        if scheme.is_referenced():
            raise ValidationError(
                'Scheme is referenced; create a new version instead of '
                'deleting.', code='referenced')
        scheme.delete()

    @staticmethod
    def supersede_rate_scheme(scheme, **overrides):
        """Thin wrapper so the viewset never writes models directly; the
        chain logic lives on RateScheme.supersede."""
        if scheme.replaced_by_id is not None:
            raise ValidationError('Scheme is already superseded.',
                                  code='superseded')
        return scheme.supersede(**overrides)


def _outbound_from_email():
    """The tenant's sending address (Configuration-first), falling back to
    the deployment default."""
    from apps.core.email_account import email_account
    return (email_account()['address']
            or getattr(settings, 'DEFAULT_FROM_EMAIL', '')
            or 'unknown@example.com')


class OutboundEmailService:
    """Sends emails via SMTP with optional attachments."""

    # Allowlist of association target fields for send_tracked.
    _ASSOC_FIELDS = ('job', 'purchase_order')

    # Fallback Message-ID domain when no `our_domain` Configuration row exists.
    DEFAULT_OUR_DOMAIN = 'example.com'

    @staticmethod
    def _resolve_our_domain():
        try:
            return Configuration.objects.get(key='our_domain').value
        except Configuration.DoesNotExist:
            return OutboundEmailService.DEFAULT_OUR_DOMAIN

    @staticmethod
    def _generate_message_id():
        import uuid
        domain = OutboundEmailService._resolve_our_domain()
        return f'<minibini-{uuid.uuid4().hex}@{domain}>'

    @staticmethod
    def _find_pending_outbound(associate_with):
        """Return the most recent outbound EmailRecord that's tied to the
        same target and has sent_at=null (a previous failed attempt)."""
        if not associate_with:
            return None
        field, target = next(iter(associate_with.items()))
        qs = EmailRecord.objects.filter(
            direction=EmailRecord.OUTBOUND,
            sent_at__isnull=True,
            **{f'{field}': target},
        ).order_by('-created_at')
        return qs.first()

    @staticmethod
    def send_tracked(*, to, subject, body, cc=None, bcc=None,
                     attachments=None, associate_with=None,
                     in_reply_to=None, references=None):
        """Persist an outbound EmailRecord + TempEmail, attempt SMTP,
        record outcome. Returns the EmailRecord regardless of send success;
        on SMTP failure the exception is re-raised after persistence.

        Args:
            to: list of recipient email addresses (or comma-separated str)
            subject: email subject line
            body: plain text email body
            cc / bcc: list[str] or None
            attachments: list of (filename, content_bytes, mime_type) tuples
            associate_with: dict of at most one of {'job': obj,
                'purchase_order': obj}, used to set the EmailRecord's FK and to find any
                pending retry row.
            in_reply_to: parent Message-ID when this is a reply (optional).
                Flows to the outgoing ``In-Reply-To`` header and the
                outbound ``TempEmail.in_reply_to`` column.
            references: thread References chain (optional). Same dual-use.

        Returns:
            EmailRecord (refreshed from DB).

        Raises:
            ValueError: associate_with has an unknown field name.
            Any exception SMTP raises (re-raised after persisting last_send_error).
        """
        if associate_with:
            field = next(iter(associate_with.keys()))
            if field not in OutboundEmailService._ASSOC_FIELDS:
                raise ValueError(
                    f'Unknown association field: {field!r}. '
                    f'Expected one of {OutboundEmailService._ASSOC_FIELDS}.'
                )

        to_list = to if isinstance(to, (list, tuple)) else [
            a.strip() for a in str(to).split(',') if a.strip()
        ]
        cc_list = list(cc or [])
        bcc_list = list(bcc or [])

        attachments_meta = [
            {'filename': fn, 'content_type': ct, 'size': len(payload)}
            for fn, payload, ct in (attachments or [])
        ]

        # Step 1: persistence — committed before SMTP so a failure leaves
        # the row in place for the user to see and retry.
        with transaction.atomic():
            existing = OutboundEmailService._find_pending_outbound(associate_with)
            if existing:
                email_record = existing
                email_record.last_send_error = ''
                email_record.save(update_fields=['last_send_error'])
                # Replace TempEmail with current form state.
                TempEmail.objects.filter(email_record=email_record).delete()
            else:
                message_id = OutboundEmailService._generate_message_id()
                assoc_kwargs = associate_with or {}
                email_record = EmailRecord.objects.create(
                    message_id=message_id,
                    direction=EmailRecord.OUTBOUND,
                    sent_at=None,
                    last_send_error='',
                    **assoc_kwargs,
                )

            TempEmail.objects.create(
                email_record=email_record,
                uid='',  # No IMAP UID for outbound
                subject=subject,
                from_email=_outbound_from_email(),
                to_email=', '.join(to_list),
                cc_email=', '.join(cc_list),
                bcc_email=', '.join(bcc_list),
                date_sent=timezone.now(),
                text_body=body or '',
                html_body='',
                attachments_metadata=attachments_meta,
                has_attachments=bool(attachments_meta),
                in_reply_to=in_reply_to or '',
                references=references or '',
            )

        # Step 2: SMTP attempt. On failure we update the row in a fresh
        # transaction so the error persists even though we re-raise.
        from django.core.mail import EmailMessage
        from apps.core.email_account import smtp_connection
        try:
            msg = EmailMessage(
                subject=subject,
                body=body,
                from_email=_outbound_from_email(),
                to=to_list,
                cc=cc_list,
                bcc=bcc_list,
                connection=smtp_connection(),  # None → default backend
            )
            msg.extra_headers['Message-ID'] = email_record.message_id
            if in_reply_to:
                msg.extra_headers['In-Reply-To'] = in_reply_to
            if references:
                msg.extra_headers['References'] = references
            for filename, content, mime_type in (attachments or []):
                msg.attach(filename, content, mime_type)
            msg.send()
        except Exception as e:
            EmailRecord.objects.filter(pk=email_record.pk).update(
                last_send_error=str(e),
            )
            raise

        EmailRecord.objects.filter(pk=email_record.pk).update(
            sent_at=timezone.now(), last_send_error='',
        )
        email_record.refresh_from_db()
        return email_record


SELF_EDIT_WINDOW_HOURS = 30


class ShiftService:
    @staticmethod
    def open_shift_for(user):
        return user.shifts.filter(end_time__isnull=True).first()

    @staticmethod
    def clock_in(user, start_time=None):
        if ShiftService.open_shift_for(user):
            raise ValidationError("You are already clocked in.")
        start = start_time or timezone.now()
        ShiftService._assert_no_overlap(user, start, None)
        from apps.core.models import Shift
        return Shift.objects.create(user=user, start_time=start)

    @staticmethod
    def ensure_open_shift(user, start_time=None):
        """Open a shift if the user has none open (auto-clock-in on blep start)."""
        existing = ShiftService.open_shift_for(user)
        if existing:
            return existing
        return ShiftService.clock_in(user, start_time=start_time)

    @staticmethod
    def clock_out(user, end_time=None):
        shift = ShiftService.open_shift_for(user)
        if not shift:
            raise ValidationError("You are not clocked in.")
        now = end_time or timezone.now()
        with transaction.atomic():
            from apps.jobs.services import BlepService
            BlepService.close_user_open_bleps(user, now=now)
            shift.end_time = now
            shift.save()
        return shift

    @staticmethod
    def _has_manage_time(user):
        return user.has_perm('core.can_manage_time')

    @staticmethod
    def _within_window(start_time):
        return (timezone.now() - start_time) <= timedelta(hours=SELF_EDIT_WINDOW_HOURS)

    @staticmethod
    def _assert_can_edit(shift, actor):
        if ShiftService._has_manage_time(actor):
            return
        if shift.user_id != actor.id:
            raise ValidationError("You can only edit your own shifts.")
        if not ShiftService._within_window(shift.start_time):
            raise ValidationError(
                "This shift is older than the edit window — request a change instead."
            )

    @staticmethod
    def _assert_encloses(user, start_time, end_time, also_span=None):
        from apps.core.time_integrity import unenclosed_bleps_for_shift
        bad = unenclosed_bleps_for_shift(user, start_time, end_time, also_span=also_span)
        if bad:
            ids = ", ".join(str(b.pk) for b in bad)
            raise ValidationError(
                f"This shift would not enclose timeslip(s) {ids}; adjust the timeslip(s) first."
            )

    @staticmethod
    def _assert_no_overlap(user, start_time, end_time, exclude_pk=None):
        """One user can't be clocked in twice at once: shifts of the same user
        may never overlap. Spans are half-open — a shift ending exactly when
        the next starts (split shifts) is legal. A null end (open shift) is
        unbounded. Inputs are minute-floored before comparing, matching what
        Shift.save() will store."""
        from django.db.models import Q
        from apps.core.timeutils import floor_to_minute
        start_time = floor_to_minute(start_time)
        end_time = floor_to_minute(end_time)
        qs = user.shifts.filter(
            Q(end_time__isnull=True) | Q(end_time__gt=start_time))
        if end_time is not None:
            qs = qs.filter(start_time__lt=end_time)
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        clash = qs.order_by('start_time').first()
        if clash:
            when = timezone.localtime(clash.start_time).strftime('%b %d, %H:%M')
            until = (timezone.localtime(clash.end_time).strftime('%H:%M')
                     if clash.end_time else 'now (still open)')
            raise ValidationError(
                f"This shift would overlap the user's shift from {when} to "
                f"{until}; shifts may not overlap."
            )

    @staticmethod
    def update(shift, actor, start_time, end_time):
        ShiftService._assert_can_edit(shift, actor)
        if end_time is not None and start_time is not None and end_time < start_time:
            raise ValidationError("End must be after start.")
        old_span = (shift.start_time, shift.end_time or timezone.now())
        ShiftService._assert_encloses(shift.user, start_time, end_time, also_span=old_span)
        ShiftService._assert_no_overlap(shift.user, start_time, end_time,
                                        exclude_pk=shift.pk)
        shift.start_time = start_time
        shift.end_time = end_time
        shift.save()
        return shift

    @staticmethod
    def create(user, actor, start_time, end_time):
        """Create a (usually historical) closed shift - used by manager edit and
        by approving a create-type change request."""
        if not (ShiftService._has_manage_time(actor) or actor.id == user.id):
            raise ValidationError("Not permitted.")
        if end_time is not None and start_time is not None and end_time < start_time:
            raise ValidationError("End must be after start.")
        ShiftService._assert_encloses(user, start_time, end_time)
        ShiftService._assert_no_overlap(user, start_time, end_time)
        from apps.core.models import Shift
        return Shift.objects.create(user=user, start_time=start_time, end_time=end_time)

    @staticmethod
    def delete(shift, actor):
        """Delete a shift — refusing while any blep it encloses would be left
        without a shift (the shift⊇blep invariant the request queue surfaces
        as 'conflicts' must survive deletion too)."""
        if not ShiftService._has_manage_time(actor):
            raise ValidationError("Deleting a shift requires can_manage_time.")
        from django.db.models import Q
        from apps.jobs.models import Blep
        enclosed = Blep.objects.filter(
            user=shift.user, start_time__gte=shift.start_time,
        )
        if shift.end_time is not None:
            enclosed = enclosed.filter(end_time__lte=shift.end_time)
        orphaned = [
            b for b in enclosed
            if not shift.user.shifts.exclude(pk=shift.pk)
                .filter(start_time__lte=b.start_time)
                .filter(Q(end_time__isnull=True) | Q(end_time__gte=b.end_time))
                .exists()
        ]
        if orphaned:
            ids = ", ".join(str(b.pk) for b in orphaned)
            raise ValidationError(
                f"Deleting this shift would leave timeslip(s) {ids} outside any "
                f"shift; move or delete them first."
            )
        shift.delete()


class TimeChangeRequestService:
    @staticmethod
    def update_request(request, actor, **fields):
        """The requester edits their own still-pending request. Reviewed
        requests are frozen; nobody else may touch it (approve/deny are the
        manager verbs, with their own endpoint + permission)."""
        from apps.core.models import TimeChangeRequest
        if request.requester_id != actor.pk:
            raise ValidationError("Only the requester may edit a request.")
        if request.status != TimeChangeRequest.STATUS_PENDING:
            raise ValidationError("This request has been reviewed and is frozen.")
        for f in ('requested_start', 'requested_end', 'reason', 'shift',
                  'blep', 'task'):
            if f in fields:
                setattr(request, f, fields[f])
        if not (request.reason or '').strip():
            raise ValidationError("A reason is required.")
        request.has_known_conflict = request.would_conflict()
        request.save()
        return request

    @staticmethod
    def submit(request):
        """Validate + save a new request. Conflicts are allowed (warn-and-flag)."""
        if not (request.reason or '').strip():
            raise ValidationError("A reason is required.")
        request.has_known_conflict = request.would_conflict()
        request.save()
        return request

    @staticmethod
    def approve(request, reviewer):
        if request.status != request.STATUS_PENDING:
            raise ValidationError("Only pending requests can be approved.")
        with transaction.atomic():
            request.apply_requested(reviewer)   # raises ValidationError on invariant break
            request.status = request.STATUS_APPROVED
            request.reviewer = reviewer
            request.reviewed_at = timezone.now()
            request.save()
        return request

    @staticmethod
    def deny(request, reviewer, note=''):
        if request.status != request.STATUS_PENDING:
            raise ValidationError("Only pending requests can be denied.")
        request.status = request.STATUS_DENIED
        request.reviewer = reviewer
        request.reviewed_at = timezone.now()
        request.review_note = note or ''
        request.save()
        return request
