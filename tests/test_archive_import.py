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
