"""Converter/importer parity for archived jobs.

Every job the nealsdata converter archives must be exactly what
``ArchiveImportService.create_archived_job`` would create from the same
translated data. The test loads ``converted.json`` into the TEST database,
builds an importer payload off each archived job (the inverse of its loaded
rows), imports a twin, and compares the two field for field.

Ignored: pks, ``job_number`` (the twin is ``<number>-P``), ``accent_color``
(both producers assign a palette colour mechanically), the document-number
``-P`` suffix the twin needs to stay unique, and run-time timestamps
(``_created`` audits and the "Imported from Kanban" marker).
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone as dt_timezone

from django.core.management import call_command
from django.test import TestCase

from apps.core.history import set_history_context
from apps.core.models import JobHistory
from apps.deliverables.models import Deliverable, Shipment
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource
from apps.inventory.models import Earmark, Material
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.jobs.archive import ArchiveImportService
from apps.jobs.models import Blep, Job, Task
from nealsdata.converter.loaders import discover_datasets
from nealsdata.converter.orchestrator import NealsDataConverter

FIXTURE = 'nealsdata/datasets/converted.json'
SOURCE = 'Kanban'
EXCLUDE_TS_ACTIONS = {f'Imported from {SOURCE}'}
LIFECYCLE_ACTIONS = {'Created', 'Started'}
TWIN_SUFFIX = '-P'

JOB_FIELDS = ('name', 'description', 'customer_po_number', 'due_date', 'created_date',
              'start_date', 'completed_date', 'project_manager_id', 'status', 'on_hold',
              'hold_reason')
TASK_FIELDS = ('name', 'description', 'sort_order', 'status', 'qty_source', 'unit_label',
               'rate', 'est_qty', 'actual_qty', 'est_worker_time', 'accounting_category_id',
               'service_item_id', 'source_scheme_id', 'active_modifiers', 'assignee_id',
               'worker_queue', 'blocked_reason', 'parent_task_id')
MATERIAL_FIELDS = ('description', 'quantity', 'units', 'unit_cost', 'sell_price',
                   'accounting_category_id', 'inventory_item_id', 'po_line_item_id',
                   'consumption_state', 'released_qty', 'cost_source')
ESTIMATE_FIELDS = ('version', 'status', 'created_date', 'sent_date', 'closed_date',
                   'expiration_date')
INVOICE_FIELDS = ('status', 'created_date', 'sent_date', 'closed_date', 'qbo_id',
                  'qbo_payment_status', 'qbo_amount_paid')
LINE_FIELDS = ('description', 'qty', 'units', 'price', 'accounting_category_id',
               'is_comment', 'line_number', 'inventory_item_id', 'adjustment_service_id',
               'adjustment_percent')
# Fields the importer never sets but converter builders can write; per model.
ESTIMATE_LINE_EXTRA = ('work_declined', 'per_unit', 'is_material', 'service_item_id')
INVOICE_LINE_EXTRA = ('agreement_estimate_line_id', 'agreement_co_line_id')


def _tasks(job):
    return list(job.tasks.order_by('sort_order', 'pk'))


def _materials(job):
    return list(Material.objects.filter(job=job).order_by('pk'))


def _estimates(job):
    return sorted(Estimate.objects.filter(job=job),
                  key=lambda e: (e.estimate_number.strip().casefold(), e.version, e.pk))


def _invoices(job):
    return list(Invoice.objects.filter(job=job).order_by('pk'))


def _line_items(doc):
    if isinstance(doc, Estimate):
        return list(EstimateLineItem.objects.filter(estimate=doc).order_by('line_number'))
    return list(InvoiceLineItem.objects.filter(invoice=doc).order_by('line_number'))


def _lines(doc):
    return [{'description': li.description, 'qty': li.qty, 'units': li.units,
             'price': li.price, 'accounting_category': li.accounting_category_id,
             'is_comment': li.is_comment}
            for li in _line_items(doc)]


def _history(job):
    """Every JobHistory row about the job or one of its children, as
    ``(row, kind, index)`` — ``index`` is the child's position in the ordered
    child list (0 for the job itself)."""
    keyed = {('job', job.pk): ('job', 0)}
    for kind, rows in (('task', _tasks(job)), ('material', _materials(job)),
                       ('estimate', _estimates(job)), ('invoice', _invoices(job)),
                       ('deliverable', list(Deliverable.objects.filter(job=job).order_by('pk'))),
                       ('shipment', list(Shipment.objects.filter(job=job).order_by('pk')))):
        for i, obj in enumerate(rows):
            keyed[(kind, obj.pk)] = (kind, i)
    out = []
    for row in JobHistory.objects.filter(object_type__in={k for k, _ in keyed}):
        hit = keyed.get((row.object_type, row.object_id))
        if hit is not None:
            out.append((row,) + hit)
    return out


def _strip(number, suffix):
    if suffix:
        assert number.endswith(suffix), number
        return number[:-len(suffix)]
    return number


class _ParityChecks:
    """The payload/snapshot machinery; subclasses load a converted fixture."""

    def _payload_from(self, job):
        """The importer payload that should recreate ``job``: the inverse of
        its loaded rows."""
        actions = [r for r, kind, _ in _history(job)
                   if kind == 'job' and r.entry_type == 'action']
        outcomes = [r.changes.get('_action') for r in actions
                    if r.changes.get('_action') not in LIFECYCLE_ACTIONS | EXCLUDE_TS_ACTIONS]
        self.assertEqual(len(outcomes), 1, f'{job.job_number}: outcome rows {outcomes}')
        notes = sorted((r for r, kind, _ in _history(job)
                        if kind == 'job' and r.entry_type == 'note'),
                       key=lambda r: (r.timestamp, r.pk))

        tasks = _tasks(job)
        task_index = {t.pk: i for i, t in enumerate(tasks)}
        return {
            'job_number': f'{job.job_number}{TWIN_SUFFIX}',
            'contact': job.contact_id,
            'project_manager': job.project_manager_id,
            'name': job.name,
            'description': job.description,
            'customer_po_number': job.customer_po_number,
            'created_date': job.created_date,
            'start_date': job.start_date,
            'due_date': job.due_date,
            'completed_date': job.completed_date,
            'outcome': outcomes[0],
            'source': SOURCE,
            'notes': [{'text': r.text, 'timestamp': r.timestamp, 'user': r.user_id}
                      for r in notes],
            'tasks': [{
                'name': t.name, 'description': t.description, 'sort_order': t.sort_order,
                'status': t.status, 'unit_label': t.unit_label, 'rate': t.rate,
                'est_qty': t.est_qty, 'actual_qty': t.actual_qty,
                'est_worker_time': t.est_worker_time,
                'accounting_category': t.accounting_category_id,
                'service_item': t.service_item_id,
            } for t in tasks],
            'materials': [{
                'description': m.description, 'quantity': m.quantity, 'units': m.units,
                'unit_cost': m.unit_cost, 'sell_price': m.sell_price,
                'accounting_category': m.accounting_category_id,
                'inventory_item': m.inventory_item_id, 'po_line_item': m.po_line_item_id,
                'task': task_index[m.task_id] if m.task_id is not None else None,
            } for m in _materials(job)],
            'estimates': [{
                'estimate_number': f'{e.estimate_number}{TWIN_SUFFIX}', 'version': e.version,
                'status': e.status, 'created_date': e.created_date, 'sent_date': e.sent_date,
                'closed_date': e.closed_date, 'expiration_date': e.expiration_date,
                'lines': _lines(e),
            } for e in _estimates(job)],
            'invoices': [{
                'invoice_number': f'{v.invoice_number}{TWIN_SUFFIX}', 'status': v.status,
                'created_date': v.created_date, 'sent_date': v.sent_date,
                'closed_date': v.closed_date, 'lines': _lines(v),
            } for v in _invoices(job)],
            'shipments': [],
        }

    def _snapshot(self, job, suffix=''):
        """Everything about ``job`` the two producers must agree on, with pks
        replaced by list indexes and run-time timestamps blanked."""
        def pick(obj, fields):
            return {f: getattr(obj, f) for f in fields}

        def lines(doc):
            extra = ESTIMATE_LINE_EXTRA if isinstance(doc, Estimate) else INVOICE_LINE_EXTRA
            return [pick(li, LINE_FIELDS + extra) for li in _line_items(doc)]

        tasks = _tasks(job)
        task_index = {t.pk: i for i, t in enumerate(tasks)}
        estimates = _estimates(job)
        est_index = {e.pk: i for i, e in enumerate(estimates)}

        history = []
        for row, kind, index in _history(job):
            action = (row.changes or {}).get('_action')
            run_time = (row.entry_type == 'audit' and (row.changes or {}).get('_created')) \
                or action in EXCLUDE_TS_ACTIONS
            history.append((
                row.entry_type, kind, index, row.user_id,
                json.dumps(row.changes, sort_keys=True, default=str), row.text,
                '' if run_time else row.timestamp.isoformat(),
            ))

        return {
            'job': pick(job, JOB_FIELDS),
            'tasks': [pick(t, TASK_FIELDS) for t in tasks],
            'materials': [
                dict(pick(m, MATERIAL_FIELDS),
                     task=task_index[m.task_id] if m.task_id is not None else None)
                for m in _materials(job)],
            'estimates': [
                dict(pick(e, ESTIMATE_FIELDS),
                     estimate_number=_strip(e.estimate_number, suffix),
                     parent=est_index[e.parent_id] if e.parent_id is not None else None,
                     lines=lines(e))
                for e in estimates],
            'invoices': [
                dict(pick(v, INVOICE_FIELDS),
                     invoice_number=_strip(v.invoice_number, suffix), lines=lines(v))
                for v in _invoices(job)],
            'counts': {
                'deliverables': Deliverable.objects.filter(job=job).count(),
                'shipments': Shipment.objects.filter(job=job).count(),
                'bleps': Blep.objects.filter(task__job=job).count(),
                'earmarks': Earmark.objects.filter(job=job).count(),
                'estimate_line_sources': EstimateLineItemSource.objects.filter(
                    estimate_line_item__estimate__job=job).count(),
                'invoice_line_sources': InvoiceLineItemSource.objects.filter(
                    invoice_line_item__invoice__job=job).count(),
            },
            'history': sorted(history),
        }

    require_archives = False

    def _assert_round_trips(self):
        archived = list(Job.objects.filter(status=Job.STATUS_ARCHIVED).order_by('pk'))
        if not archived and not self.require_archives:
            # Time-based rule over regenerated inputs: zero archives is legitimate.
            self.skipTest('no archived jobs at this clock')
        self.assertGreater(len(archived), 0)
        zero = dict.fromkeys(('deliverables', 'shipments', 'bleps', 'earmarks',
                              'estimate_line_sources', 'invoice_line_sources'), 0)
        self.maxDiff = None
        for job in archived:
            twin = ArchiveImportService.create_archived_job(self._payload_from(job), user=None)
            mine = self._snapshot(job)
            self.assertEqual(mine['counts'], zero, job.job_number)
            self.assertEqual(mine, self._snapshot(twin, suffix=TWIN_SUFFIX), job.job_number)


@unittest.skipUnless(os.path.exists(FIXTURE), 'converted.json not generated')
class ConverterImporterParityTest(_ParityChecks, TestCase):
    """Every archived job the converter emits must be reproducible, field for
    field, by ArchiveImportService from a payload built off that job
    (spec §2 goals: RM's archive testing on converted data must be valid)."""

    @classmethod
    def setUpTestData(cls):
        call_command('loaddata', FIXTURE, verbosity=0)
        set_history_context(None)

    def test_every_archived_job_round_trips_through_the_importer(self):
        self._assert_round_trips()


try:
    XLSX, CSV = discover_datasets('nealsdata/datasets')
except (ValueError, FileNotFoundError):
    XLSX = CSV = None


@unittest.skipUnless(XLSX and CSV and os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class FarFutureParityTest(_ParityChecks, TestCase):
    """The same parity over a conversion run with a far-future clock, so every
    closed job archives — breadth converted.json's handful of old jobs lacks
    (materials, superseded estimate chains, cancelled tasks)."""

    require_archives = True

    @classmethod
    def setUpTestData(cls):
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        try:
            NealsDataConverter(XLSX, CSV, output_path=path,
                               now=datetime(2030, 1, 1, tzinfo=dt_timezone.utc)).convert()
            call_command('loaddata', path, verbosity=0)
        finally:
            os.unlink(path)
        set_history_context(None)

    def test_every_archived_job_round_trips_through_the_importer(self):
        self._assert_round_trips()
