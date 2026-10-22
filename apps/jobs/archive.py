"""Archived-job import (archived-jobs spec §4, §5).

``ArchiveImportService.create_archived_job`` turns one plain-dict payload into
an ``archived`` Job with its children, in one transaction. Everything is
written with ORM ``create()`` — never the domain services, whose guards and
status-coupled side effects are exactly what a historical import must avoid —
so model ``save()`` hooks (``@history`` ``_created`` audits, Material's
``_populate_from_pli``, Task/Deliverable sort-order assignment) still run.

The whole payload is validated before any write; every problem is collected
into one ``ValidationError`` keyed by payload path (``'tasks[2].status'``) so
an importer can map errors back to source rows.
"""
import math
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime, parse_duration

from apps.core.history import (
    HistoryContext, get_history_context, record_history, set_history_context,
)
from apps.jobs.models import Job, Task


# Upper bound for imported durations (100,000 hours) — well past any real
# task, far below timedelta's overflow.
MAX_DURATION_SECONDS = 100_000 * 3600


def _blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _add(errors, path, message):
    errors.setdefault(path, []).append(message)


class ArchiveImportService:
    TASK_STATUSES = (Task.STATUS_COMPLETE, Task.STATUS_CANCELLED)
    DATE_FIELDS = ('created_date', 'start_date', 'due_date', 'completed_date')
    # Every recognised top-level payload key (spec §4). Anything else is a
    # payload error — a typo'd key ('invoice') would otherwise silently drop
    # data. Nested row keys stay permissive.
    PAYLOAD_KEYS = frozenset((
        'job_number', 'contact', 'project_manager', 'name', 'description',
        'customer_po_number', 'outcome', 'source', 'notes',
        'tasks', 'materials', 'deliverables', 'shipments', 'estimates', 'invoices',
    ) + DATE_FIELDS)

    # ------------------------------------------------------------------ entry
    @staticmethod
    def create_archived_job(payload, *, user=None):
        S = ArchiveImportService
        errors = S._validate(payload)
        if errors:
            raise ValidationError(errors)

        prev = get_history_context()
        ctx = HistoryContext(user=user)
        set_history_context(ctx)
        try:
            with transaction.atomic():
                job = S._create_job(payload, user)
                tasks = S._create_tasks(job, payload.get('tasks') or [])
                deliverables = S._create_deliverables(job, payload.get('deliverables') or [])
                S._create_materials(job, payload.get('materials') or [], tasks)
                S._create_estimates(job, payload.get('estimates') or [])
                S._create_invoices(job, payload.get('invoices') or [])
                S._create_shipments(job, payload.get('shipments') or [], deliverables)
                # Inside the atomic block so a rollback discards these rows too.
                S._flush_history(ctx, user)
                S._write_history(job, payload, user, ctx)
        finally:
            set_history_context(prev)
        return job

    # ------------------------------------------------------------- coercion
    @staticmethod
    def _coerce_dt(value, path, errors):
        """ISO datetime/date string, ``datetime`` or ``date`` → aware datetime.
        ``None``/blank → ``None``. Naive values take the current timezone."""
        if _blank(value):
            return None
        dt = None
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, date):
            dt = datetime.combine(value, time.min)
        elif isinstance(value, str):
            try:
                dt = parse_datetime(value.strip())
                if dt is None:
                    d = parse_date(value.strip())
                    if d is not None:
                        dt = datetime.combine(d, time.min)
            except ValueError:
                dt = None
        if dt is None:
            _add(errors, path, 'Enter a valid date/time.')
            return None
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
        return dt

    @staticmethod
    def _coerce_decimal(value, path, errors, *, positive=False, non_negative=False):
        if _blank(value):
            return None
        if isinstance(value, bool):
            _add(errors, path, 'Enter a number.')
            return None
        try:
            d = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            _add(errors, path, 'Enter a number.')
            return None
        if not d.is_finite():
            _add(errors, path, 'Enter a number.')
            return None
        # Magnitude first: quantize() raises InvalidOperation on values whose
        # coefficient would exceed the context precision (e.g. '1e30').
        if abs(d) >= Decimal('100000000'):
            _add(errors, path, 'This number is too large.')
            return None
        if d != d.quantize(Decimal('0.01')):
            _add(errors, path, 'Use at most 2 decimal places.')
            return None
        if positive and d <= 0:
            _add(errors, path, 'Must be greater than zero.')
            return None
        if non_negative and d < 0:
            _add(errors, path, 'Must not be negative.')
            return None
        return d.quantize(Decimal('0.01'))

    @staticmethod
    def _coerce_duration(value, path, errors):
        """Seconds (number) or ISO-8601 / Django duration string → timedelta."""
        if _blank(value):
            return None
        if isinstance(value, timedelta):
            return value
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            try:
                seconds = float(value)
            except (OverflowError, ValueError):
                seconds = math.inf
            if not math.isfinite(seconds):
                _add(errors, path, 'Enter a duration in seconds or ISO-8601 (e.g. PT2H).')
                return None
            if seconds < 0:
                _add(errors, path, 'Must not be negative.')
                return None
            if seconds > MAX_DURATION_SECONDS:
                _add(errors, path, 'This duration is too large.')
                return None
            return timedelta(seconds=seconds)
        if isinstance(value, str):
            try:
                td = parse_duration(value.strip())
            except (OverflowError, ValueError):
                td = None
            if td is not None and td > timedelta(seconds=MAX_DURATION_SECONDS):
                _add(errors, path, 'This duration is too large.')
                return None
            if td is not None and td >= timedelta(0):
                return td
        _add(errors, path, 'Enter a duration in seconds or ISO-8601 (e.g. PT2H).')
        return None

    @staticmethod
    def _coerce_str(value, path, errors, *, max_length=None, required=False):
        if value is None:
            value = ''
        if not isinstance(value, str):
            _add(errors, path, 'Must be text.')
            return ''
        if required and not value.strip():
            _add(errors, path, 'This field is required.')
        if max_length is not None and len(value) > max_length:
            _add(errors, path, f'Must be at most {max_length} characters.')
        return value

    @staticmethod
    def _resolve(model, value, path, errors, label, *, required=False):
        """pk → instance, reporting 'Unknown <label> <pk>.' for misses."""
        if value is None or value == '':
            if required:
                _add(errors, path, 'This field is required.')
            return None
        if isinstance(value, bool):
            _add(errors, path, f'Unknown {label} {value}.')
            return None
        try:
            obj = model.objects.filter(pk=value).first()
        except (ValueError, TypeError):
            obj = None
        if obj is None:
            _add(errors, path, f'Unknown {label} {value}.')
        return obj

    @staticmethod
    def _rows(payload, key, errors, *, path=None):
        """``(index, row)`` for each dict in ``payload[key]``; ``path`` is the
        error-path prefix for nested lists (defaults to ``key``)."""
        path = path or key
        rows = payload.get(key)
        if rows is None:
            return []
        if not isinstance(rows, list):
            _add(errors, path, 'Must be a list.')
            return []
        good = []
        for i, row in enumerate(rows):
            if isinstance(row, dict):
                good.append((i, row))
            else:
                _add(errors, f'{path}[{i}]', 'Must be an object.')
        return good

    @staticmethod
    def _document_statuses():
        from apps.deliverables.models import Shipment
        from apps.estimates.models import Estimate
        from apps.invoicing.models import Invoice
        return {
            'estimates': (Estimate.STATUS_ACCEPTED, Estimate.STATUS_REJECTED,
                          Estimate.STATUS_EXPIRED),
            'invoices': (Invoice.STATUS_PAID, Invoice.STATUS_CANCELLED),
            'shipments': (Shipment.STATUS_PICKED_UP,),
        }

    # ------------------------------------------------------------- validate
    @staticmethod
    def _validate(payload):
        from apps.contacts.models import Contact
        from apps.core.models import AccountingCategory, User
        from apps.estimates.models import ServiceItem
        from apps.inventory.models import InventoryItem
        from apps.purchasing.models import PurchaseOrderLineItem

        S = ArchiveImportService
        errors = {}
        if not isinstance(payload, dict):
            return {'non_field_errors': ['The payload must be an object.']}

        unknown = [k for k in payload if k not in S.PAYLOAD_KEYS]
        if unknown:
            _add(errors, 'non_field_errors',
                 f'Unknown payload keys: {", ".join(str(k) for k in unknown)}.')

        # Header
        job_number = payload.get('job_number')
        if _blank(job_number):
            _add(errors, 'job_number', 'This field is required.')
        else:
            job_number = S._coerce_str(job_number, 'job_number', errors, max_length=50)
            if 'job_number' not in errors and Job.objects.filter(job_number=job_number).exists():
                _add(errors, 'job_number', f'A job numbered {job_number} already exists.')
        S._resolve(Contact, payload.get('contact'), 'contact', errors, 'contact', required=True)
        S._resolve(User, payload.get('project_manager'), 'project_manager', errors, 'user')
        S._coerce_str(payload.get('name'), 'name', errors, max_length=50)
        S._coerce_str(payload.get('description'), 'description', errors)
        S._coerce_str(payload.get('customer_po_number'), 'customer_po_number', errors, max_length=50)
        S._coerce_str(payload.get('outcome'), 'outcome', errors)
        S._coerce_str(payload.get('source'), 'source', errors)
        for f in S.DATE_FIELDS:
            S._coerce_dt(payload.get(f), f, errors)

        # Notes
        for i, note in S._rows(payload, 'notes', errors):
            p = f'notes[{i}]'
            S._coerce_str(note.get('text'), f'{p}.text', errors, required=True)
            S._coerce_dt(note.get('timestamp'), f'{p}.timestamp', errors)
            S._resolve(User, note.get('user'), f'{p}.user', errors, 'user')

        # Tasks
        task_rows = S._rows(payload, 'tasks', errors)
        n_tasks = len(payload.get('tasks')) if isinstance(payload.get('tasks'), list) else 0
        for i, t in task_rows:
            p = f'tasks[{i}]'
            S._coerce_str(t.get('name'), f'{p}.name', errors, max_length=255, required=True)
            S._coerce_str(t.get('description'), f'{p}.description', errors)
            status = t.get('status')
            if status is not None and status not in S.TASK_STATUSES:
                _add(errors, f'{p}.status',
                     f'An archived task must be complete or cancelled, not {status!r}.')
            if t.get('unit_label') is not None:
                S._coerce_str(t.get('unit_label'), f'{p}.unit_label', errors,
                              max_length=50, required=True)
            so = t.get('sort_order')
            if so is not None and (isinstance(so, bool) or not isinstance(so, int) or so < 0):
                _add(errors, f'{p}.sort_order', 'Must be a whole number of 0 or more.')
            S._coerce_decimal(t.get('rate'), f'{p}.rate', errors)
            S._coerce_decimal(t.get('est_qty'), f'{p}.est_qty', errors, non_negative=True)
            S._coerce_decimal(t.get('actual_qty'), f'{p}.actual_qty', errors, non_negative=True)
            S._coerce_duration(t.get('est_worker_time'), f'{p}.est_worker_time', errors)
            S._resolve(AccountingCategory, t.get('accounting_category'),
                       f'{p}.accounting_category', errors, 'accounting category')
            S._resolve(ServiceItem, t.get('service_item'), f'{p}.service_item', errors, 'service item')

        # Deliverables
        for i, d in S._rows(payload, 'deliverables', errors):
            p = f'deliverables[{i}]'
            S._coerce_str(d.get('description'), f'{p}.description', errors, required=True)
            if _blank(d.get('qty_ordered')):
                _add(errors, f'{p}.qty_ordered', 'This field is required.')
            else:
                S._coerce_decimal(d.get('qty_ordered'), f'{p}.qty_ordered', errors, positive=True)
            if d.get('units') is not None:
                S._coerce_str(d.get('units'), f'{p}.units', errors, max_length=50, required=True)
            so = d.get('sort_order')
            if so is not None and (isinstance(so, bool) or not isinstance(so, int) or so < 0):
                _add(errors, f'{p}.sort_order', 'Must be a whole number of 0 or more.')

        # Materials
        for i, m in S._rows(payload, 'materials', errors):
            p = f'materials[{i}]'
            S._coerce_str(m.get('description'), f'{p}.description', errors, max_length=255)
            if m.get('units') is not None:
                S._coerce_str(m.get('units'), f'{p}.units', errors, max_length=50, required=True)
            S._coerce_decimal(m.get('quantity'), f'{p}.quantity', errors, non_negative=True)
            S._coerce_decimal(m.get('unit_cost'), f'{p}.unit_cost', errors, non_negative=True)
            S._coerce_decimal(m.get('sell_price'), f'{p}.sell_price', errors, non_negative=True)
            S._resolve(InventoryItem, m.get('inventory_item'),
                              f'{p}.inventory_item', errors, 'inventory item')
            has_item = m.get('inventory_item') not in (None, '')
            S._resolve(AccountingCategory, m.get('accounting_category'),
                       f'{p}.accounting_category', errors, 'accounting category',
                       required=not has_item)
            S._resolve(PurchaseOrderLineItem, m.get('po_line_item'),
                       f'{p}.po_line_item', errors, 'purchase order line')
            idx = m.get('task')
            if idx is not None and (isinstance(idx, bool) or not isinstance(idx, int)
                                    or not 0 <= idx < n_tasks):
                _add(errors, f'{p}.task',
                     f'Task index {idx!r} does not match any of the {n_tasks} task(s) in this payload.')

        S._validate_documents(payload, errors)
        S._validate_shipments(payload, errors)
        return errors

    @staticmethod
    def _validate_lines(row, path, errors):
        """A document's ``lines``: ``{description, qty, units, price,
        accounting_category, is_comment}``. Comment lines carry no money."""
        from apps.core.models import AccountingCategory
        S = ArchiveImportService
        for j, line in S._rows(row, 'lines', errors, path=f'{path}.lines'):
            lp = f'{path}.lines[{j}]'
            S._coerce_str(line.get('description'), f'{lp}.description', errors)
            if line.get('units') is not None:
                S._coerce_str(line.get('units'), f'{lp}.units', errors,
                              max_length=50, required=True)
            qty = S._coerce_decimal(line.get('qty'), f'{lp}.qty', errors)
            price = S._coerce_decimal(line.get('price'), f'{lp}.price', errors)
            S._resolve(AccountingCategory, line.get('accounting_category'),
                       f'{lp}.accounting_category', errors, 'accounting category')
            is_comment = line.get('is_comment', False)
            if not isinstance(is_comment, bool):
                _add(errors, f'{lp}.is_comment', 'Must be true or false.')
            elif is_comment:
                if qty:
                    _add(errors, f'{lp}.qty', 'A comment line cannot have a quantity.')
                if price:
                    _add(errors, f'{lp}.price', 'A comment line cannot have a price.')

    @staticmethod
    def _validate_documents(payload, errors):
        """Estimates and invoices: settled status, a number unique in the DB
        and within the payload (spec §3.9), dates, lines."""
        from apps.estimates.models import Estimate
        from apps.invoicing.models import Invoice
        S = ArchiveImportService
        statuses = S._document_statuses()
        specs = (
            ('estimates', 'estimate_number', 'estimate',
             lambda n: Estimate.objects.filter(estimate_number=n).exists(),
             ('created_date', 'sent_date', 'closed_date', 'expiration_date')),
            ('invoices', 'invoice_number', 'invoice',
             lambda n: Invoice.objects.filter(invoice_number=n).exists(),
             ('created_date', 'sent_date', 'closed_date')),
        )
        for key, num_field, label, taken, date_fields in specs:
            allowed = statuses[key]
            if key == 'estimates':
                allowed = allowed + (Estimate.STATUS_SUPERSEDED,)
            seen = set()
            accepted = 0
            chains = {}  # casefolded number -> [(index, version, status)]
            for i, row in S._rows(payload, key, errors):
                p = f'{key}[{i}]'
                np = f'{p}.{num_field}'
                number = row.get(num_field)
                version = 1
                version_ok = True
                if key == 'estimates':
                    raw_version = row.get('version', 1)
                    if (isinstance(raw_version, bool) or not isinstance(raw_version, int)
                            or raw_version < 1):
                        _add(errors, f'{p}.version', 'Must be a whole number, 1 or more.')
                        version_ok = False
                    else:
                        version = raw_version
                number_ok = False
                if _blank(number):
                    _add(errors, np, 'This field is required.')
                else:
                    before = len(errors.get(np, []))
                    number = S._coerce_str(number, np, errors, max_length=50)
                    if len(errors.get(np, [])) == before:
                        # Case/whitespace-insensitive, matching MySQL's
                        # collation on the unique column.
                        key_ = number.strip().casefold()
                        seen_key = (key_, version)
                        if seen_key in seen:
                            _add(errors, np, f'{label.capitalize()} number {number} appears '
                                             f'more than once in this payload.')
                        elif taken(number):
                            _add(errors, np, f'An {label} numbered {number} already exists.')
                        else:
                            number_ok = True
                        seen.add(seen_key)
                status = row.get('status')
                if _blank(status):
                    _add(errors, f'{p}.status', 'This field is required.')
                elif status not in allowed:
                    _add(errors, f'{p}.status',
                         f'An archived {label} must be {" or ".join(allowed)}, not {status!r}.')
                elif key == 'estimates':
                    if status == Estimate.STATUS_ACCEPTED:
                        accepted += 1
                    if number_ok and version_ok:
                        chains.setdefault(key_, []).append((i, version, status))
                for f in date_fields:
                    S._coerce_dt(row.get(f), f'{p}.{f}', errors)
                S._validate_lines(row, p, errors)
            for members in chains.values():
                S._validate_chain(members, errors)
            if accepted > 1:
                _add(errors, 'estimates', 'At most one accepted estimate.')

    @staticmethod
    def _validate_chain(members, errors):
        """Rows sharing an estimate number: versions 1..k, lower versions
        superseded, the highest settled."""
        from apps.estimates.models import Estimate
        members = sorted(members, key=lambda m: m[1])
        for pos, (i, version, _status) in enumerate(members, start=1):
            if version != pos:
                _add(errors, f'estimates[{i}].version',
                     'Estimate versions must be contiguous from 1.')
                return
        *lower, (top_i, _top_v, top_status) = members
        for i, _v, status in lower:
            if status != Estimate.STATUS_SUPERSEDED:
                _add(errors, f'estimates[{i}].status',
                     'Lower versions of an estimate must be superseded.')
        if top_status == Estimate.STATUS_SUPERSEDED:
            _add(errors, f'estimates[{top_i}].status',
                 'The latest version of an estimate must be accepted, rejected or expired.')

    @staticmethod
    def _validate_shipments(payload, errors):
        """Picked-up shipments of this payload's deliverables; total shipped
        per deliverable never exceeds its ``qty_ordered``."""
        S = ArchiveImportService
        deliverables = payload.get('deliverables')
        deliverables = deliverables if isinstance(deliverables, list) else []
        scratch = {}
        ordered = [
            S._coerce_decimal(d.get('qty_ordered'), '', scratch) if isinstance(d, dict) else None
            for d in deliverables
        ]
        n = len(deliverables)
        shipped = {}
        allowed = S._document_statuses()['shipments']
        for i, row in S._rows(payload, 'shipments', errors):
            p = f'shipments[{i}]'
            status = row.get('status')
            if status is not None and status not in allowed:
                _add(errors, f'{p}.status',
                     f'An archived shipment must be picked up, not {status!r}.')
            if _blank(row.get('picked_up_date')):
                _add(errors, f'{p}.picked_up_date', 'This field is required.')
            else:
                S._coerce_dt(row.get('picked_up_date'), f'{p}.picked_up_date', errors)
            S._coerce_dt(row.get('prepared_date'), f'{p}.prepared_date', errors)
            S._coerce_str(row.get('notes'), f'{p}.notes', errors)
            items = S._rows(row, 'items', errors, path=f'{p}.items')
            if not items and f'{p}.items' not in errors:
                _add(errors, f'{p}.items', 'A shipment needs at least one item.')
            in_this = set()
            for j, item in items:
                ip = f'{p}.items[{j}]'
                idx = item.get('deliverable')
                if (idx is None or isinstance(idx, bool) or not isinstance(idx, int)
                        or not 0 <= idx < n):
                    _add(errors, f'{ip}.deliverable',
                         f'Deliverable index {idx!r} does not match any of the {n} '
                         f'deliverable(s) in this payload.')
                    idx = None
                elif idx in in_this:
                    _add(errors, f'{ip}.deliverable',
                         'This deliverable is already in this shipment.')
                    idx = None
                else:
                    in_this.add(idx)
                if _blank(item.get('qty')):
                    _add(errors, f'{ip}.qty', 'This field is required.')
                    continue
                qty = S._coerce_decimal(item.get('qty'), f'{ip}.qty', errors, positive=True)
                if qty is None or idx is None or ordered[idx] is None:
                    continue
                shipped[idx] = shipped.get(idx, Decimal('0')) + qty
                if shipped[idx] > ordered[idx]:
                    _add(errors, f'{ip}.qty',
                         f'Ships {shipped[idx]} in total of deliverable {idx}, '
                         f'which only ordered {ordered[idx]}.')

    # --------------------------------------------------------------- create
    @staticmethod
    def _create_job(payload, user):
        S = ArchiveImportService
        scratch = {}
        fields = dict(
            job_number=payload['job_number'],
            contact_id=payload['contact'],
            status=Job.STATUS_ARCHIVED,
            name=payload.get('name') or '',
            description=payload.get('description') or '',
            customer_po_number=payload.get('customer_po_number') or '',
            project_manager_id=payload.get('project_manager') or None,
        )
        for f in S.DATE_FIELDS:
            dt = S._coerce_dt(payload.get(f), f, scratch)
            if dt is not None:
                fields[f] = dt
        return Job.objects.create(**fields)

    @staticmethod
    def _create_tasks(job, rows):
        S = ArchiveImportService
        scratch = {}
        tasks = []
        for t in rows:
            tasks.append(Task.objects.create(
                job=job,
                name=t['name'],
                description=t.get('description') or '',
                sort_order=t.get('sort_order'),
                status=t.get('status') or Task.STATUS_COMPLETE,
                qty_source=Task.QTY_ENTERED,
                unit_label=t.get('unit_label') or 'none',
                rate=S._coerce_decimal(t.get('rate'), '', scratch),
                est_qty=S._coerce_decimal(t.get('est_qty'), '', scratch),
                actual_qty=S._coerce_decimal(t.get('actual_qty'), '', scratch),
                est_worker_time=S._coerce_duration(t.get('est_worker_time'), '', scratch),
                accounting_category_id=t.get('accounting_category') or None,
                service_item_id=t.get('service_item') or None,
            ))
        return tasks

    @staticmethod
    def _create_deliverables(job, rows):
        from apps.deliverables.models import Deliverable
        S = ArchiveImportService
        scratch = {}
        out = []
        for d in rows:
            out.append(Deliverable.objects.create(
                job=job,
                description=d['description'],
                qty_ordered=S._coerce_decimal(d['qty_ordered'], '', scratch),
                units=d.get('units') or 'none',
                sort_order=d.get('sort_order') or 0,  # 0 → save() assigns
            ))
        return out

    @staticmethod
    def _create_materials(job, rows, tasks):
        from apps.inventory.models import Material
        S = ArchiveImportService
        scratch = {}
        zero = Decimal('0.00')
        out = []
        for m in rows:
            idx = m.get('task')
            out.append(Material.objects.create(
                job=job,
                task=tasks[idx] if idx is not None else None,
                description=m.get('description') or '',
                quantity=S._coerce_decimal(m.get('quantity'), '', scratch) or zero,
                units=m.get('units') or 'none',
                unit_cost=S._coerce_decimal(m.get('unit_cost'), '', scratch) or zero,
                sell_price=S._coerce_decimal(m.get('sell_price'), '', scratch) or zero,
                accounting_category_id=m.get('accounting_category') or None,
                inventory_item_id=m.get('inventory_item') or None,
                po_line_item_id=m.get('po_line_item') or None,
                consumption_state=Material.CONSUMPTION_STATE_CONSUMED,
                released_qty=zero,
                cost_source=Material.COST_SOURCE_IMPORTED,
            ))
        return out

    @staticmethod
    def _create_lines(model, parent_field, parent, rows):
        S = ArchiveImportService
        scratch = {}
        zero = Decimal('0.00')
        for n, line in enumerate(rows, start=1):
            model.objects.create(**{
                parent_field: parent,
                'line_number': n,
                'description': line.get('description') or '',
                'qty': S._coerce_decimal(line.get('qty'), '', scratch) or zero,
                'units': line.get('units') or 'none',
                'price': S._coerce_decimal(line.get('price'), '', scratch) or zero,
                'accounting_category_id': line.get('accounting_category') or None,
                'is_comment': bool(line.get('is_comment', False)),
            })

    @staticmethod
    def _dates(row, fields):
        S = ArchiveImportService
        scratch = {}
        return {f: S._coerce_dt(row.get(f), '', scratch) for f in fields}

    @staticmethod
    def _create_estimates(job, rows):
        """Created straight at a settled status: Estimate.save's status hooks
        (crystallisation, claim release, job status) fire only on a *change*."""
        from apps.estimates.models import Estimate, EstimateLineItem
        S = ArchiveImportService
        out = []
        fields = ('created_date', 'sent_date', 'closed_date', 'expiration_date')
        ordered = sorted(rows, key=lambda r: (r['estimate_number'].strip().casefold(),
                                              r.get('version', 1)))
        previous = None
        for n, e in enumerate(ordered):
            dates = S._dates(e, fields)
            dates['created_date'] = dates['created_date'] or timezone.now()
            version = e.get('version', 1)
            parent = None
            if (previous is not None and version > 1
                    and previous.estimate_number.strip().casefold()
                    == e['estimate_number'].strip().casefold()):
                parent = previous
            if e['status'] == Estimate.STATUS_SUPERSEDED and dates['closed_date'] is None:
                successor = S._dates(ordered[n + 1], fields)['created_date'] if n + 1 < len(ordered) else None
                dates['closed_date'] = successor or dates['created_date']
            est = Estimate.objects.create(
                job=job, estimate_number=e['estimate_number'], version=version,
                parent=parent, status=e['status'], **dates)
            previous = est
            S._create_lines(EstimateLineItem, 'estimate', est, e.get('lines') or [])
            out.append(est)
        return out

    @staticmethod
    def _create_invoices(job, rows):
        """Created at ``paid``/``cancelled``: ``_maybe_complete_job`` and claim
        release fire only on a status change. ``Invoice.save`` runs ``clean()``
        but not ``full_clean`` — number uniqueness rests on ``_validate``."""
        from apps.invoicing.models import Invoice, InvoiceLineItem
        S = ArchiveImportService
        out = []
        for v in rows:
            dates = S._dates(v, ('created_date', 'sent_date', 'closed_date'))
            dates['created_date'] = dates['created_date'] or timezone.now()
            if v['status'] == Invoice.STATUS_PAID and dates['closed_date'] is None:
                dates['closed_date'] = dates['created_date']
            inv = Invoice.objects.create(
                job=job, invoice_number=v['invoice_number'], status=v['status'], **dates)
            S._create_lines(InvoiceLineItem, 'invoice', inv, v.get('lines') or [])
            out.append(inv)
        return out

    @staticmethod
    def _create_shipments(job, rows, deliverables):
        from apps.deliverables.models import Shipment, ShipmentItem
        S = ArchiveImportService
        scratch = {}
        out = []
        for i, sh in enumerate(rows):
            dates = S._dates(sh, ('picked_up_date', 'prepared_date'))
            shipment = Shipment.objects.create(
                job=job, sequence=i + 1, status=Shipment.STATUS_PICKED_UP,
                picked_up_date=dates['picked_up_date'],
                prepared_date=dates['prepared_date'] or dates['picked_up_date'],
                notes=sh.get('notes') or '',
            )
            for item in sh['items']:
                ShipmentItem.objects.create(
                    shipment=shipment, deliverable=deliverables[item['deliverable']],
                    qty=S._coerce_decimal(item['qty'], '', scratch))
            out.append(shipment)
        return out

    # -------------------------------------------------------------- history
    @staticmethod
    def _flush_history(ctx, user):
        """Write the ``@history`` audits queued on ``ctx`` (the body of
        ``HistoryMiddleware._flush_pending`` with an explicit author)."""
        for entry_data in ctx.pending:
            instance = entry_data.pop('_instance', None)
            is_new = entry_data.pop('_is_new', False)
            object_id = entry_data.get('object_id')
            if is_new and instance is not None:
                object_id = instance.pk
            if not object_id:
                continue
            record_history(
                object_type=entry_data['object_type'],
                entry_type=entry_data['entry_type'],
                object_id=object_id,
                changes=entry_data['changes'],
                text=entry_data.get('text', ''),
                user=user,
            )
        ctx.pending.clear()

    @staticmethod
    def _write_history(job, payload, user, ctx=None):
        """Backdated lifecycle ``action`` rows, the ``Imported`` marker, and
        notes (spec §5.7)."""
        from apps.core.models import User
        S = ArchiveImportService
        scratch = {}

        def action(text, when=None):
            record_history(object_type='job', entry_type='action', object_id=job.pk,
                           user=user, changes={'_action': text}, timestamp=when)

        action('Created', job.created_date)
        if job.start_date:
            action('Started', job.start_date)
        if job.completed_date:
            action(payload.get('outcome') or 'Closed', job.completed_date)
        source = (payload.get('source') or '').strip()
        action(f'Imported from {source}' if source else 'Imported')

        for note in payload.get('notes') or []:
            author = user
            if note.get('user') not in (None, ''):
                author = User.objects.get(pk=note['user'])
            record_history(
                object_type='job', entry_type='note', object_id=job.pk, user=author,
                text=note['text'],
                timestamp=S._coerce_dt(note.get('timestamp'), '', scratch),
            )
