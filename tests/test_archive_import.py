"""ArchiveImportService (archived-jobs spec §4, §5.1-5.3, §5.7): one call
creates an archived job and its children from a plain dict payload."""
from datetime import timedelta
from unittest import mock
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.core.history import HistoryContext, get_history_context, set_history_context
from apps.core.models import AccountingCategory, JobHistory, User
from apps.deliverables.models import Deliverable
from apps.inventory.models import Earmark, InventoryItem, Material
from apps.jobs.archive import ArchiveImportService
from apps.jobs.models import Job, Task
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from tests.test_contacts_status import make_business


def _created_audits(object_type, object_id):
    return [
        h for h in JobHistory.objects.filter(
            entry_type='audit', object_type=object_type, object_id=object_id)
        if (h.changes or {}).get('_created')
    ]


def _actions(job):
    return {
        h.changes['_action']: h
        for h in JobHistory.objects.filter(entry_type='action', object_type='job', object_id=job.pk)
    }


class ArchiveImportTestBase(TestCase):
    def setUp(self):
        set_history_context(None)
        self.business, self.contact, _ = make_business('Arch', n_contacts=1)
        self.category = AccountingCategory.objects.create(code='MAT', name='Materials')
        self.user = User.objects.create_user(username='importer', password='x')

    def tearDown(self):
        set_history_context(None)

    def create(self, payload):
        return ArchiveImportService.create_archived_job(payload, user=self.user)

    def assertErrorKeys(self, payload, *keys):
        with self.assertRaises(ValidationError) as cm:
            self.create(payload)
        d = cm.exception.message_dict
        for k in keys:
            self.assertIn(k, d, f'{k} not in {d}')
            self.assertTrue(all(isinstance(m, str) and m for m in d[k]))
        return d


class HeaderTests(ArchiveImportTestBase):
    def test_minimal_payload_creates_archived_job(self):
        before = timezone.now()
        job = self.create({'job_number': 'OLD-1', 'contact': self.contact.pk})
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_ARCHIVED)
        self.assertEqual(job.name, '')
        self.assertLessEqual(abs(job.created_date - before), timedelta(seconds=5))
        self.assertIsNone(job.start_date)
        self.assertIsNone(job.completed_date)

        audits = _created_audits('job', job.pk)
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].user, self.user)

        actions = _actions(job)
        self.assertEqual(set(actions), {'Created', 'Imported'})
        self.assertEqual(
            JobHistory.objects.filter(entry_type='action', object_id=job.pk, object_type='job').count(), 2)
        self.assertEqual(actions['Created'].timestamp, job.created_date)

    def test_inactive_contact_is_allowed(self):
        self.contact.is_active = False
        self.contact.save()
        job = self.create({'job_number': 'OLD-2', 'contact': self.contact.pk})
        self.assertEqual(job.contact_id, self.contact.pk)
        self.assertEqual(job.status, Job.STATUS_ARCHIVED)

    def test_missing_required_and_unknown_contact(self):
        self.assertErrorKeys({}, 'job_number', 'contact')
        d = self.assertErrorKeys({'job_number': 'OLD-3', 'contact': 999999}, 'contact')
        self.assertEqual(set(d), {'contact'})
        self.assertEqual(Job.objects.count(), 0)

    def test_duplicate_job_number_is_a_field_error(self):
        Job.objects.create(job_number='LIVE-1', contact=self.contact)
        jobs_before = Job.objects.count()
        history_before = JobHistory.objects.count()
        d = self.assertErrorKeys({'job_number': 'LIVE-1', 'contact': self.contact.pk}, 'job_number')
        self.assertEqual(set(d), {'job_number'})
        self.assertEqual(Job.objects.count(), jobs_before)
        self.assertEqual(JobHistory.objects.count(), history_before)

    def test_header_fields_and_dates_land_as_given(self):
        pm = User.objects.create_user(username='pm', password='x')
        now = timezone.now().replace(microsecond=0)
        created = now - timedelta(days=730)
        started = created + timedelta(days=3)
        completed = created + timedelta(days=30)
        due = created + timedelta(days=20)
        job = self.create({
            'job_number': 'OLD-4', 'contact': self.contact.pk,
            'name': 'Old cabinet', 'description': 'Walnut cabinets',
            'customer_po_number': 'CPO-9', 'project_manager': pm.pk,
            'created_date': created.isoformat(), 'start_date': started,
            'due_date': due.isoformat(), 'completed_date': completed.isoformat(),
        })
        job.refresh_from_db()
        self.assertEqual(job.name, 'Old cabinet')
        self.assertEqual(job.description, 'Walnut cabinets')
        self.assertEqual(job.customer_po_number, 'CPO-9')
        self.assertEqual(job.project_manager, pm)
        self.assertEqual(job.created_date, created)
        self.assertEqual(job.start_date, started)
        self.assertEqual(job.due_date, due)
        self.assertEqual(job.completed_date, completed)

    def test_naive_datetime_string_is_made_aware_and_bad_date_rejected(self):
        job = self.create({'job_number': 'OLD-5', 'contact': self.contact.pk,
                           'start_date': '2023-04-02T09:30:00'})
        job.refresh_from_db()
        self.assertTrue(timezone.is_aware(job.start_date))
        self.assertEqual(timezone.localtime(job.start_date).hour, 9)
        self.assertErrorKeys({'job_number': 'OLD-6', 'contact': self.contact.pk,
                              'due_date': 'not a date'}, 'due_date')


class ChildTests(ArchiveImportTestBase):
    def test_tasks_are_terminal_entered_quantity(self):
        job = self.create({
            'job_number': 'OLD-T', 'contact': self.contact.pk,
            'tasks': [
                {'name': 'Cut', 'status': 'cancelled'},
                {'name': 'Assemble', 'unit_label': 'hour', 'actual_qty': 12.5,
                 'rate': '85.00', 'est_qty': '10', 'est_worker_time': 'PT2H',
                 'accounting_category': self.category.pk},
            ],
        })
        tasks = list(job.tasks.order_by('sort_order'))
        self.assertEqual([t.name for t in tasks], ['Cut', 'Assemble'])
        self.assertLess(tasks[0].sort_order, tasks[1].sort_order)
        self.assertEqual(tasks[0].status, Task.STATUS_CANCELLED)
        self.assertEqual(tasks[1].status, Task.STATUS_COMPLETE)
        for t in tasks:
            self.assertEqual(t.qty_source, Task.QTY_ENTERED)
        self.assertEqual(tasks[0].unit_label, 'none')
        self.assertEqual(tasks[1].get_actual_qty(), Decimal('12.50'))
        self.assertEqual(tasks[1].rate, Decimal('85.00'))
        self.assertEqual(tasks[1].est_worker_time, timedelta(hours=2))
        self.assertEqual(tasks[1].accounting_category, self.category)

        self.assertErrorKeys({'job_number': 'OLD-T2', 'contact': self.contact.pk,
                              'tasks': [{'name': 'x', 'status': 'pending'}]}, 'tasks[0].status')
        self.assertErrorKeys({'job_number': 'OLD-T3', 'contact': self.contact.pk,
                              'tasks': [{'status': 'complete'}]}, 'tasks[0].name')

    def test_deliverables_and_materials(self):
        self.assertErrorKeys({'job_number': 'OLD-D1', 'contact': self.contact.pk,
                              'deliverables': [{'description': 'Box', 'qty_ordered': 0}]},
                             'deliverables[0].qty_ordered')
        self.assertErrorKeys({'job_number': 'OLD-D2', 'contact': self.contact.pk,
                              'tasks': [{'name': 'Only'}],
                              'materials': [{'description': 'Ply', 'task': 5,
                                             'accounting_category': self.category.pk}]},
                             'materials[0].task')
        self.assertErrorKeys({'job_number': 'OLD-D3', 'contact': self.contact.pk,
                              'materials': [{'description': 'Ply'}]},
                             'materials[0].accounting_category')

        item = InventoryItem.objects.create(
            code='PLY-34', description='3/4 ply', units='sheet',
            purchase_price=Decimal('40.00'), selling_price=Decimal('60.00'),
            qty_on_hand=Decimal('7.00'), accounting_category=self.category)
        po = PurchaseOrder.objects.create(business=self.business, po_number='PO-ARCH')
        pol = PurchaseOrderLineItem.objects.create(
            purchase_order=po, line_number=1, description='ply', qty=Decimal('2'),
            price=Decimal('40.00'), units='sheet')
        earmarks_before = Earmark.objects.count()

        job = self.create({
            'job_number': 'OLD-D4', 'contact': self.contact.pk,
            'tasks': [{'name': 'Build'}],
            'deliverables': [{'description': 'Cabinet', 'qty_ordered': '2'}],
            'materials': [
                {'description': 'Glue', 'quantity': '1.5', 'units': 'bottle',
                 'unit_cost': '4.00', 'sell_price': '6.00',
                 'accounting_category': self.category.pk, 'task': 0},
                {'inventory_item': item.pk, 'quantity': '2', 'po_line_item': pol.pk},
            ],
        })
        task = job.tasks.get()
        d = job.deliverables.get()
        self.assertEqual(d.qty_ordered, Decimal('2.00'))
        self.assertEqual(d.units, 'none')

        glue = job.materials.get(description='Glue')
        self.assertEqual(glue.task, task)
        self.assertEqual(glue.quantity, Decimal('1.50'))
        self.assertEqual(glue.unit_cost, Decimal('4.00'))
        ply = job.materials.get(inventory_item=item)
        self.assertEqual(ply.po_line_item, pol)
        self.assertEqual(ply.accounting_category, self.category)
        self.assertEqual(ply.unit_cost, Decimal('40.00'))
        for m in (glue, ply):
            self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)
            self.assertEqual(m.cost_source, Material.COST_SOURCE_IMPORTED)
            self.assertEqual(m.released_qty, Decimal('0.00'))
        self.assertEqual(Earmark.objects.count(), earmarks_before)
        item.refresh_from_db()
        self.assertEqual(item.qty_on_hand, Decimal('7.00'))


class HistoryTests(ArchiveImportTestBase):
    def test_backdated_history_and_notes(self):
        author = User.objects.create_user(username='author', password='x')
        created = (timezone.now() - timedelta(days=400)).replace(microsecond=0)
        started = created + timedelta(days=2)
        completed = created + timedelta(days=40)
        note_at = created + timedelta(days=5)
        before = timezone.now()
        job = self.create({
            'job_number': 'OLD-H', 'contact': self.contact.pk,
            'created_date': created, 'start_date': started, 'completed_date': completed,
            'outcome': 'Completed in Fishbowl', 'source': 'Fishbowl',
            'notes': [
                {'text': 'Customer called about finish', 'timestamp': note_at.isoformat(),
                 'user': author.pk},
                {'text': 'Imported without photos'},
            ],
            'tasks': [{'name': 'Cut'}],
            'deliverables': [{'description': 'Box', 'qty_ordered': 1}],
            'materials': [{'description': 'Glue', 'accounting_category': self.category.pk}],
        })
        actions = _actions(job)
        self.assertEqual(set(actions),
                         {'Created', 'Started', 'Completed in Fishbowl', 'Imported from Fishbowl'})
        self.assertEqual(actions['Created'].timestamp, created)
        self.assertEqual(actions['Started'].timestamp, started)
        self.assertEqual(actions['Completed in Fishbowl'].timestamp, completed)
        self.assertLessEqual(abs(actions['Imported from Fishbowl'].timestamp - before), timedelta(seconds=5))
        for a in actions.values():
            self.assertEqual(a.user, self.user)

        notes = {n.text: n for n in JobHistory.objects.filter(
            entry_type='note', object_type='job', object_id=job.pk)}
        self.assertEqual(set(notes), {'Customer called about finish', 'Imported without photos'})
        self.assertEqual(notes['Customer called about finish'].timestamp, note_at)
        self.assertEqual(notes['Customer called about finish'].user, author)
        self.assertEqual(notes['Imported without photos'].user, self.user)
        self.assertLessEqual(abs(notes['Imported without photos'].timestamp - before), timedelta(seconds=5))

        targets = [('job', job.pk), ('task', job.tasks.get().pk),
                   ('material', job.materials.get().pk), ('deliverable', job.deliverables.get().pk)]
        for object_type, pk in targets:
            audits = _created_audits(object_type, pk)
            self.assertEqual(len(audits), 1, object_type)
            self.assertEqual(audits[0].user, self.user, object_type)

    def test_outcome_defaults_to_closed_only_with_completed_date(self):
        done = timezone.now() - timedelta(days=100)
        job = self.create({'job_number': 'OLD-H2', 'contact': self.contact.pk, 'completed_date': done})
        self.assertIn('Closed', _actions(job))
        job2 = self.create({'job_number': 'OLD-H3', 'contact': self.contact.pk, 'outcome': 'Done'})
        self.assertEqual(set(_actions(job2)), {'Created', 'Imported'})

    def test_failure_after_valid_rows_writes_nothing(self):
        counts = (Job.objects.count(), Task.objects.count(), JobHistory.objects.count())
        self.assertErrorKeys({
            'job_number': 'OLD-F', 'contact': self.contact.pk,
            'tasks': [{'name': 'A'}, {'name': 'B'}, {'name': 'C', 'status': 'pending'}],
        }, 'tasks[2].status')
        self.assertEqual((Job.objects.count(), Task.objects.count(), JobHistory.objects.count()), counts)

    def test_error_during_writes_rolls_back_rows_and_history(self):
        counts = (Job.objects.count(), Task.objects.count(), JobHistory.objects.count())
        with mock.patch.object(ArchiveImportService, '_create_materials',
                               side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.create({'job_number': 'OLD-R', 'contact': self.contact.pk,
                             'tasks': [{'name': 'A'}]})
        self.assertEqual((Job.objects.count(), Task.objects.count(), JobHistory.objects.count()), counts)
        self.assertIsNone(get_history_context())

    def test_history_context_is_restored(self):
        sentinel = HistoryContext()
        set_history_context(sentinel)
        self.create({'job_number': 'OLD-C1', 'contact': self.contact.pk})
        self.assertIs(get_history_context(), sentinel)
        self.assertEqual(sentinel.pending, [])
        with self.assertRaises(ValidationError):
            self.create({'job_number': 'OLD-C2'})
        self.assertIs(get_history_context(), sentinel)


class DocumentTests(ArchiveImportTestBase):
    """Task 8b — settled estimates, invoices and picked-up shipments (§5.4-5.6)."""

    def base(self, number, **extra):
        return {'job_number': number, 'contact': self.contact.pk, **extra}

    def test_estimates_created_without_side_effects(self):
        from apps.estimates.models import Estimate, EstimateLineItemSource
        sources_before = EstimateLineItemSource.objects.count()
        earmarks_before = Earmark.objects.count()
        created = (timezone.now() - timedelta(days=300)).replace(microsecond=0)
        sent = created + timedelta(days=1)
        closed = created + timedelta(days=5)
        job = self.create(self.base('OLD-E1', estimates=[
            {'estimate_number': 'EST-OLD-1', 'status': 'accepted',
             'created_date': created, 'sent_date': sent.isoformat(), 'closed_date': closed,
             'expiration_date': created + timedelta(days=30),
             'lines': [
                 {'description': 'Cabinet', 'qty': '2', 'units': 'each', 'price': '500.00',
                  'accounting_category': self.category.pk},
                 {'description': 'Walnut finish', 'is_comment': True},
             ]},
            {'estimate_number': 'EST-OLD-2', 'status': 'rejected',
             'lines': [{'description': 'Alt', 'qty': 1, 'price': 900}]},
        ]))
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_ARCHIVED)
        ests = {e.estimate_number: e for e in Estimate.objects.filter(job=job)}
        self.assertEqual(set(ests), {'EST-OLD-1', 'EST-OLD-2'})
        acc = ests['EST-OLD-1']
        self.assertEqual(acc.status, Estimate.STATUS_ACCEPTED)
        self.assertEqual(ests['EST-OLD-2'].status, Estimate.STATUS_REJECTED)
        for e in ests.values():
            self.assertEqual(e.version, 1)
            self.assertIsNone(e.parent)
            self.assertTrue(e.public_token)
        self.assertEqual(acc.created_date, created)
        self.assertEqual(acc.sent_date, sent)
        self.assertEqual(acc.closed_date, closed)
        lines = list(acc.estimatelineitem_set.order_by('line_number'))
        self.assertEqual([l.line_number for l in lines], [1, 2])
        self.assertEqual(lines[0].qty, Decimal('2.00'))
        self.assertEqual(lines[0].price, Decimal('500.00'))
        self.assertEqual(lines[0].units, 'each')
        self.assertEqual(lines[0].accounting_category, self.category)
        self.assertTrue(lines[1].is_comment)
        self.assertEqual(lines[1].qty, Decimal('0.00'))
        self.assertEqual(EstimateLineItemSource.objects.count(), sources_before)
        self.assertEqual(Earmark.objects.count(), earmarks_before)
        self.assertEqual(job.tasks.count(), 0)  # acceptance crystallised nothing
        self.assertEqual(len(_created_audits('estimate', acc.pk)), 1)

        self.assertErrorKeys(self.base('OLD-E2', estimates=[
            {'estimate_number': 'EST-D', 'status': 'draft'}]), 'estimates[0].status')
        d = self.assertErrorKeys(self.base('OLD-E3', estimates=[
            {'estimate_number': 'EST-A1', 'status': 'accepted'},
            {'estimate_number': 'EST-A2', 'status': 'accepted'}]), 'estimates')
        self.assertEqual(set(d), {'estimates'})
        self.assertErrorKeys(self.base('OLD-E4', estimates=[
            {'estimate_number': 'EST-C', 'status': 'rejected',
             'lines': [{'description': 'note', 'is_comment': True, 'price': '5'}]}]),
            'estimates[0].lines[0].price')
        self.assertEqual(Job.objects.filter(job_number__in=['OLD-E2', 'OLD-E3', 'OLD-E4']).count(), 0)

    def test_estimate_number_collision(self):
        from apps.estimates.models import Estimate
        live = Job.objects.create(job_number='LIVE-E', contact=self.contact)
        Estimate.objects.create(job=live, estimate_number='EST-DUP', version=1)
        counts = (Job.objects.count(), Estimate.objects.count())
        d = self.assertErrorKeys(self.base('OLD-EC', estimates=[
            {'estimate_number': 'EST-DUP', 'status': 'expired'}]), 'estimates[0].estimate_number')
        self.assertEqual(set(d), {'estimates[0].estimate_number'})
        d = self.assertErrorKeys(self.base('OLD-EC', estimates=[
            {'estimate_number': 'EST-SAME', 'status': 'expired'},
            {'estimate_number': 'EST-SAME', 'status': 'rejected'}]), 'estimates[1].estimate_number')
        self.assertNotIn('estimates[0].estimate_number', d)
        self.assertErrorKeys(self.base('OLD-EC', estimates=[{'status': 'expired'}]),
                             'estimates[0].estimate_number')
        self.assertEqual((Job.objects.count(), Estimate.objects.count()), counts)

    def test_version_chain_creates_superseded_parents(self):
        from apps.estimates.models import Estimate
        created = (timezone.now() - timedelta(days=400)).replace(microsecond=0)
        job = self.create(self.base('OLD-V1', estimates=[
            {'estimate_number': 'EST-V', 'version': 1, 'status': 'superseded',
             'created_date': created, 'lines': [{'description': 'a', 'qty': 1, 'price': 10}]},
            {'estimate_number': 'EST-V', 'version': 2, 'status': 'superseded',
             'created_date': created + timedelta(days=3), 'closed_date': created + timedelta(days=9),
             'lines': [{'description': 'b', 'qty': 1, 'price': 20}]},
            {'estimate_number': 'EST-V', 'version': 3, 'status': 'accepted',
             'created_date': created + timedelta(days=10),
             'lines': [{'description': 'c', 'qty': 1, 'price': 30}]},
        ]))
        v = {e.version: e for e in Estimate.objects.filter(job=job)}
        self.assertEqual(set(v), {1, 2, 3})
        self.assertEqual(v[1].status, Estimate.STATUS_SUPERSEDED)
        self.assertEqual(v[2].status, Estimate.STATUS_SUPERSEDED)
        self.assertEqual(v[3].status, Estimate.STATUS_ACCEPTED)
        self.assertIsNone(v[1].parent)
        self.assertEqual(v[2].parent, v[1])
        self.assertEqual(v[3].parent, v[2])
        # superseded without closed_date defaults to the successor's created_date
        self.assertEqual(v[1].closed_date, v[2].created_date)
        self.assertEqual(v[2].closed_date, created + timedelta(days=9))
        self.assertEqual(v[3].estimatelineitem_set.count(), 1)

    def test_version_chain_validation(self):
        def chain(*rows):
            return [{'estimate_number': 'EST-X', **r} for r in rows]
        # non-contiguous
        self.assertErrorKeys(self.base('OLD-V2', estimates=chain(
            {'version': 1, 'status': 'superseded'}, {'version': 3, 'status': 'accepted'})),
            'estimates[1].version')
        # duplicate (number, version)
        self.assertErrorKeys(self.base('OLD-V3', estimates=chain(
            {'version': 1, 'status': 'superseded'}, {'version': 1, 'status': 'accepted'})),
            'estimates[1].estimate_number')
        # lower version not superseded
        self.assertErrorKeys(self.base('OLD-V4', estimates=chain(
            {'version': 1, 'status': 'rejected'}, {'version': 2, 'status': 'accepted'})),
            'estimates[0].status')
        # highest version superseded
        self.assertErrorKeys(self.base('OLD-V5', estimates=chain(
            {'version': 1, 'status': 'superseded'}, {'version': 2, 'status': 'superseded'})),
            'estimates[1].status')
        # a lone version-1 estimate may not be superseded
        self.assertErrorKeys(self.base('OLD-V6', estimates=chain(
            {'version': 1, 'status': 'superseded'})), 'estimates[0].status')
        # bad version values
        self.assertErrorKeys(self.base('OLD-V7', estimates=chain(
            {'version': 0, 'status': 'accepted'})), 'estimates[0].version')
        self.assertErrorKeys(self.base('OLD-V8', estimates=chain(
            {'version': 'two', 'status': 'accepted'})), 'estimates[0].version')
        self.assertEqual(Job.objects.filter(job_number__startswith='OLD-V').count(), 0)

    def test_number_taken_at_any_version_is_refused(self):
        from apps.estimates.models import Estimate
        live = Job.objects.create(job_number='LIVE-V', contact=self.contact)
        Estimate.objects.create(job=live, estimate_number='EST-T', version=2)
        self.assertErrorKeys(self.base('OLD-V9', estimates=[
            {'estimate_number': 'EST-T', 'status': 'expired'}]), 'estimates[0].estimate_number')

    def test_two_chains_in_one_payload(self):
        from apps.estimates.models import Estimate
        job = self.create(self.base('OLD-V10', estimates=[
            {'estimate_number': 'EST-P', 'version': 1, 'status': 'superseded'},
            {'estimate_number': 'EST-Q', 'version': 1, 'status': 'rejected'},
            {'estimate_number': 'EST-P', 'version': 2, 'status': 'accepted'},
        ]))
        p2 = Estimate.objects.get(job=job, estimate_number='EST-P', version=2)
        self.assertEqual(p2.parent.estimate_number, 'EST-P')
        self.assertIsNone(Estimate.objects.get(job=job, estimate_number='EST-Q').parent)

    def test_invoices_created_settled(self):
        from apps.invoicing.models import Invoice, InvoiceLineItemSource
        sources_before = InvoiceLineItemSource.objects.count()
        created = (timezone.now() - timedelta(days=200)).replace(microsecond=0)
        job = self.create(self.base('OLD-I1', invoices=[
            {'invoice_number': '1001', 'status': 'paid', 'created_date': created,
             'sent_date': created + timedelta(days=1),
             'lines': [{'description': 'Cabinets', 'qty': 1, 'price': '1200.00',
                        'accounting_category': self.category.pk}]},
            {'invoice_number': '1002', 'status': 'cancelled',
             'lines': [{'description': 'Wrong', 'qty': 1, 'price': 50}]},
        ]))
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_ARCHIVED)
        paid = Invoice.objects.get(invoice_number='1001')
        cancelled = Invoice.objects.get(invoice_number='1002')
        self.assertEqual(paid.job, job)
        self.assertEqual(paid.status, Invoice.STATUS_PAID)
        self.assertEqual(paid.created_date, created)
        self.assertEqual(paid.closed_date, created)
        self.assertEqual(paid.sent_date, created + timedelta(days=1))
        self.assertEqual(paid.display_number, '1001')
        self.assertIsNone(paid.qbo_id)
        self.assertEqual(cancelled.status, Invoice.STATUS_CANCELLED)
        self.assertIsNone(cancelled.closed_date)
        line = paid.invoicelineitem_set.get()
        self.assertEqual((line.line_number, line.price), (1, Decimal('1200.00')))
        self.assertEqual(InvoiceLineItemSource.objects.count(), sources_before)
        self.assertEqual(len(_created_audits('invoice', paid.pk)), 1)

        self.assertErrorKeys(self.base('OLD-I2', invoices=[
            {'invoice_number': '2001', 'status': 'open'}]), 'invoices[0].status')
        self.assertErrorKeys(self.base('OLD-I3', invoices=[{'status': 'paid'}]),
                             'invoices[0].invoice_number')
        counts = (Job.objects.count(), Invoice.objects.count(), JobHistory.objects.count())
        d = self.assertErrorKeys(self.base('OLD-I4', invoices=[
            {'invoice_number': '1001', 'status': 'paid'}]), 'invoices[0].invoice_number')
        self.assertEqual(set(d), {'invoices[0].invoice_number'})
        self.assertErrorKeys(self.base('OLD-I5', invoices=[
            {'invoice_number': '3001', 'status': 'paid'},
            {'invoice_number': '3001', 'status': 'cancelled'}]), 'invoices[1].invoice_number')
        self.assertEqual((Job.objects.count(), Invoice.objects.count(), JobHistory.objects.count()),
                         counts)

    def test_shipments_picked_up_with_items(self):
        from apps.deliverables.models import Shipment, ShipmentItem
        picked = (timezone.now() - timedelta(days=100)).replace(microsecond=0)
        prepared = picked - timedelta(days=2)
        deliverables = [{'description': 'Cabinet', 'qty_ordered': 2},
                        {'description': 'Shelf', 'qty_ordered': '4'}]
        job = self.create(self.base('OLD-S1', deliverables=deliverables, shipments=[
            {'picked_up_date': picked, 'notes': 'First load',
             'items': [{'deliverable': 0, 'qty': 1}, {'deliverable': 1, 'qty': '4'}]},
            {'status': 'picked_up', 'picked_up_date': picked + timedelta(days=7),
             'prepared_date': prepared + timedelta(days=7),
             'items': [{'deliverable': 0, 'qty': 1}]},
        ]))
        ships = list(Shipment.objects.filter(job=job).order_by('sequence'))
        self.assertEqual([s.sequence for s in ships], [1, 2])
        for s in ships:
            self.assertEqual(s.status, Shipment.STATUS_PICKED_UP)
        self.assertEqual(ships[0].picked_up_date, picked)
        self.assertEqual(ships[0].prepared_date, picked)
        self.assertEqual(ships[0].notes, 'First load')
        self.assertEqual(ships[1].prepared_date, prepared + timedelta(days=7))
        cab = job.deliverables.get(description='Cabinet')
        shelf = job.deliverables.get(description='Shelf')
        self.assertEqual(
            {(i.deliverable_id, i.qty) for i in ShipmentItem.objects.filter(shipment=ships[0])},
            {(cab.pk, Decimal('1.00')), (shelf.pk, Decimal('4.00'))})
        self.assertEqual(ShipmentItem.objects.get(shipment=ships[1]).deliverable, cab)
        self.assertEqual(len(_created_audits('shipment', ships[0].pk)), 1)

        counts = (Job.objects.count(), Shipment.objects.count())
        self.assertErrorKeys(self.base('OLD-S2', deliverables=deliverables, shipments=[
            {'status': 'prepared', 'picked_up_date': picked,
             'items': [{'deliverable': 0, 'qty': 1}]}]), 'shipments[0].status')
        self.assertErrorKeys(self.base('OLD-S3', deliverables=deliverables, shipments=[
            {'items': [{'deliverable': 0, 'qty': 1}]}]), 'shipments[0].picked_up_date')
        d = self.assertErrorKeys(self.base('OLD-S4', deliverables=deliverables, shipments=[
            {'picked_up_date': picked, 'items': [{'deliverable': 0, 'qty': 2}]},
            {'picked_up_date': picked, 'items': [{'deliverable': 0, 'qty': 1}]}]),
            'shipments[1].items[0].qty')
        self.assertEqual(set(d), {'shipments[1].items[0].qty'})
        self.assertErrorKeys(self.base('OLD-S5', deliverables=deliverables, shipments=[
            {'picked_up_date': picked, 'items': [{'deliverable': 9, 'qty': 1}]}]),
            'shipments[0].items[0].deliverable')
        self.assertErrorKeys(self.base('OLD-S6', deliverables=deliverables, shipments=[
            {'picked_up_date': picked, 'items': [{'deliverable': 0, 'qty': 0}]}]),
            'shipments[0].items[0].qty')
        self.assertErrorKeys(self.base('OLD-S7', deliverables=deliverables, shipments=[
            {'picked_up_date': picked, 'items': []}]), 'shipments[0].items')
        self.assertEqual((Job.objects.count(), Shipment.objects.count()), counts)

    def test_full_payload_round_trip(self):
        from apps.deliverables.models import Shipment
        from apps.estimates.models import Estimate
        from apps.invoicing.models import Invoice
        from apps.jobs.financials import compute_job_financials, spend_breakdown
        from apps.jobs.services import JobService
        created = (timezone.now() - timedelta(days=90)).replace(microsecond=0)
        job = self.create(self.base(
            'OLD-FULL', name='Kitchen', created_date=created,
            start_date=created + timedelta(days=3), completed_date=created + timedelta(days=30),
            outcome='Completed', source='Paper',
            notes=[{'text': 'All good'}],
            tasks=[{'name': 'Build', 'unit_label': 'hour', 'actual_qty': '12.5', 'rate': '80'},
                   {'name': 'Parts', 'unit_label': 'piece', 'actual_qty': '3'}],
            deliverables=[{'description': 'Cabinet', 'qty_ordered': 2}],
            materials=[{'description': 'Glue', 'quantity': 1, 'unit_cost': '4.00',
                        'accounting_category': self.category.pk, 'task': 0}],
            estimates=[{'estimate_number': 'EST-FULL', 'status': 'accepted',
                        'lines': [{'description': 'Kitchen', 'qty': 1, 'price': 1500}]}],
            invoices=[
                {'invoice_number': 'INV-FULL-1', 'status': 'paid',
                 'lines': [{'description': 'Deposit', 'qty': 1, 'price': '700.00'},
                           {'description': 'Balance', 'qty': 2, 'price': '400.00'},
                           {'description': 'Thanks', 'is_comment': True}]},
                {'invoice_number': 'INV-FULL-2', 'status': 'cancelled',
                 'lines': [{'description': 'Void', 'qty': 1, 'price': '999.00'}]},
            ],
            shipments=[{'picked_up_date': created + timedelta(days=29),
                        'items': [{'deliverable': 0, 'qty': 2}]}],
        ))
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_ARCHIVED)
        fin = compute_job_financials(job)
        self.assertEqual(fin['invoiced'], Decimal('1500.00'))
        self.assertEqual(spend_breakdown(job)['labor_hours'], Decimal('12.50'))

        counts = (Estimate.objects.count(), Invoice.objects.count(), Shipment.objects.count())
        dup = JobService.duplicate_job(job, contact=job.contact, path='estimate')
        self.assertEqual(dup.status, Job.STATUS_DRAFT)
        self.assertEqual(sorted(dup.tasks.values_list('name', flat=True)), ['Build', 'Parts'])
        self.assertEqual(list(dup.materials.values_list('description', flat=True)), ['Glue'])
        self.assertEqual(list(dup.deliverables.values_list('description', flat=True)), ['Cabinet'])
        self.assertFalse(Estimate.objects.filter(job=dup).exists())
        self.assertFalse(Invoice.objects.filter(job=dup).exists())
        self.assertFalse(Shipment.objects.filter(job=dup).exists())
        self.assertEqual(
            (Estimate.objects.count(), Invoice.objects.count(), Shipment.objects.count()), counts)


class InputHardeningTests(ArchiveImportTestBase):
    """Final-review F2/F6: hostile inputs become path-keyed errors, never an
    uncaught exception or a mid-write IntegrityError; nothing is written."""

    def base(self, number, **extra):
        return {'job_number': number, 'contact': self.contact.pk, **extra}

    def counts(self):
        from apps.estimates.models import Estimate
        from apps.invoicing.models import Invoice
        return (Job.objects.count(), Task.objects.count(), Material.objects.count(),
                Estimate.objects.count(), Invoice.objects.count(), JobHistory.objects.count())

    def test_huge_exponent_quantity_is_a_field_error(self):
        before = self.counts()
        d = self.assertErrorKeys(self.base('OLD-H1', tasks=[
            {'name': 'Cut', 'status': 'complete', 'est_qty': '1e30'}]), 'tasks[0].est_qty')
        self.assertIn('This number is too large.', d['tasks[0].est_qty'])
        d = self.assertErrorKeys(self.base('OLD-H1', materials=[
            {'description': 'Ply', 'quantity': '1e30'}]), 'materials[0].quantity')
        self.assertIn('This number is too large.', d['materials[0].quantity'])
        self.assertEqual(self.counts(), before)

    def test_non_finite_and_huge_duration_is_a_field_error(self):
        before = self.counts()
        for bad in (float('inf'), float('nan'), 10 ** 400, 10 ** 12):
            with self.subTest(bad=bad):
                self.assertErrorKeys(self.base('OLD-H2', tasks=[
                    {'name': 'Cut', 'status': 'complete', 'est_worker_time': bad}]),
                    'tasks[0].est_worker_time')
        self.assertEqual(self.counts(), before)

    def test_case_variant_estimate_numbers_in_one_payload(self):
        before = self.counts()
        d = self.assertErrorKeys(self.base('OLD-H3', estimates=[
            {'estimate_number': 'EST-1', 'status': 'rejected'},
            {'estimate_number': 'est-1', 'status': 'expired'}]), 'estimates[1].estimate_number')
        self.assertNotIn('estimates[0].estimate_number', d)
        self.assertEqual(self.counts(), before)

    def test_case_variant_invoice_numbers_in_one_payload(self):
        before = self.counts()
        d = self.assertErrorKeys(self.base('OLD-H4', invoices=[
            {'invoice_number': 'INV-A', 'status': 'paid'},
            {'invoice_number': ' inv-a ', 'status': 'cancelled'}]), 'invoices[1].invoice_number')
        self.assertNotIn('invoices[0].invoice_number', d)
        self.assertEqual(self.counts(), before)

    def test_unknown_top_level_keys_are_a_non_field_error(self):
        before = self.counts()
        d = self.assertErrorKeys(self.base('OLD-H5', invoice=[
            {'invoice_number': '9', 'status': 'paid'}], foo=1), 'non_field_errors')
        self.assertEqual(d['non_field_errors'], ['Unknown payload keys: invoice, foo.'])
        self.assertEqual(self.counts(), before)
