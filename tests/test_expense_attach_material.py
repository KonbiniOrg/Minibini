"""Path 2: attaching an expense to an existing material prices AND receives.

Attach == receipt: supplying the cost also backs the material with stock and
stamps EXPENSE provenance, establishing a provisional target in the process.
See docs spec §Path 2. Entry point is ExpenseService.submit (not .create).
"""
from decimal import Decimal
from datetime import date

from django.test import TestCase, Client
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from apps.core.models import AccountingCategory, Configuration
from apps.expenses.models import Expense
from apps.expenses.services import ExpenseService
from apps.inventory.models import Material
from apps.inventory.services import MaterialService

User = get_user_model()


def _seed_job_config():
    Configuration.objects.update_or_create(
        key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'},
    )
    Configuration.objects.update_or_create(
        key='job_counter', defaults={'value': '0'},
    )
    Configuration.objects.update_or_create(
        key='default_material_markup_percent', defaults={'value': '25'},
    )


class ExpenseAttachTests(TestCase):
    def setUp(self):
        _seed_job_config()
        from apps.contacts.models import Contact
        from apps.jobs.models import Job
        self.user = User.objects.create_user(username='worker', password='testpass')
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Shop Supplies', qbo_expense_account_id='500',
        )
        self.contact = Contact.objects.create(
            first_name='T', last_name='C', email='c@test.com',
        )
        self.job = Job.objects.create(job_number='JOB-A1', contact=self.contact)

    def _attach(self, *, amount, material_id, attach_qty=None, description='x'):
        return ExpenseService.submit(
            entered_by=self.user, purchased_by=self.user, amount=amount,
            purchased_on=date(2026, 4, 1), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            description=description, material_id=material_id, attach_qty=attach_qty,
        )

    def test_attach_to_established_receives_and_reprices(self):
        m = MaterialService.create_on_job(
            job=self.job, description='ply', quantity=Decimal('4'),
            unit_cost=Decimal('50.00'), accounting_category=self.cat, units='ea')
        self.assertIsNotNone(m.inventory_item_id)  # born established (priced)
        e = self._attach(amount=Decimal('240.00'), material_id=m.pk,
                         description='bought at yard')
        m.refresh_from_db()
        self.assertEqual(e.material_id, m.pk)
        self.assertEqual(m.unit_cost, Decimal('60.00'))          # 240/4
        self.assertEqual(m.cost_source, Material.COST_SOURCE_EXPENSE)
        self.assertEqual(m.inventory_item.qty_on_hand, Decimal('4'))  # attach == receipt

    def test_attach_to_provisional_establishes(self):
        m = MaterialService.create_on_job(
            job=self.job, description='mystery', quantity=Decimal('2'),
            accounting_category=self.cat, units='ea')
        self.assertIsNone(m.inventory_item_id)  # provisional
        self._attach(amount=Decimal('30.00'), material_id=m.pk,
                     description='corner store')
        m.refresh_from_db()
        self.assertIsNotNone(m.inventory_item_id)
        self.assertEqual(m.unit_cost, Decimal('15.00'))          # 30/2
        self.assertEqual(m.cost_source, Material.COST_SOURCE_EXPENSE)
        self.assertEqual(m.inventory_item.qty_on_hand, Decimal('2'))

    def test_attach_partial_qty_tops_up(self):
        m = MaterialService.create_on_job(
            job=self.job, description='ply', quantity=Decimal('12'),
            unit_cost=Decimal('10.00'), accounting_category=self.cat, units='ea')
        # Pretend a partial PO receipt already landed 8 units.
        m.inventory_item.qty_on_hand = Decimal('8')
        m.inventory_item.save()
        self._attach(amount=Decimal('44.00'), material_id=m.pk,
                     attach_qty=Decimal('4'), description='last 4 locally')
        m.refresh_from_db()
        self.assertEqual(m.inventory_item.qty_on_hand, Decimal('12'))  # 8 + 4
        self.assertEqual(m.unit_cost, Decimal('11.00'))               # 44/4

    def test_attach_refuses_customer_supplied(self):
        # Task 10 adds create_on_job(customer_supplied=True); until then, build
        # the customer material by stamping COST_SOURCE_CUSTOMER directly. The
        # refusal path under test is real now.
        m = MaterialService.create_on_job(
            job=self.job, description='theirs', quantity=Decimal('1'),
            accounting_category=self.cat, units='ea')
        m.cost_source = Material.COST_SOURCE_CUSTOMER
        m.save(update_fields=['cost_source'])
        with self.assertRaises(ValidationError):
            self._attach(amount=Decimal('5.00'), material_id=m.pk)

    def test_attach_refuses_nonpending(self):
        m = MaterialService.create_on_job(
            job=self.job, description='done', quantity=Decimal('1'),
            unit_cost=Decimal('3.00'), accounting_category=self.cat, units='ea')
        m.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        m.save(update_fields=['consumption_state'])
        with self.assertRaises(ValidationError):
            self._attach(amount=Decimal('5.00'), material_id=m.pk)

    def test_attach_mutually_exclusive_with_new_material(self):
        m = MaterialService.create_on_job(
            job=self.job, description='ply', quantity=Decimal('1'),
            unit_cost=Decimal('3.00'), accounting_category=self.cat, units='ea')
        with self.assertRaises(ValidationError):
            ExpenseService.submit(
                entered_by=self.user, purchased_by=self.user,
                amount=Decimal('5.00'), purchased_on=date(2026, 4, 1),
                accounting_category=self.cat,
                payment_method=Expense.PAYMENT_METHOD_PERSONAL,
                material_id=m.pk,
                new_material={'job_id': self.job.pk, 'description': 'z',
                              'quantity': 1, 'price': Decimal('5.00')})

    def test_attach_zero_qty_rejected(self):
        m = MaterialService.create_on_job(
            job=self.job, description='ply', quantity=Decimal('4'),
            unit_cost=Decimal('50.00'), accounting_category=self.cat, units='ea')
        with self.assertRaises(ValidationError):
            self._attach(amount=Decimal('5.00'), material_id=m.pk,
                         attach_qty=Decimal('0'))

    def test_attach_sets_expense_job_from_material(self):
        m = MaterialService.create_on_job(
            job=self.job, description='ply', quantity=Decimal('2'),
            unit_cost=Decimal('5.00'), accounting_category=self.cat, units='ea')
        e = self._attach(amount=Decimal('20.00'), material_id=m.pk)
        self.assertEqual(e.job_id, self.job.pk)


class ExpenseAttachRejectTest(TestCase):
    """Reject unwinds an attach: reverses the stock receipt and clears EXPENSE
    provenance, but the pre-existing material itself survives (it predates the
    expense)."""

    def setUp(self):
        _seed_job_config()
        from apps.contacts.models import Contact
        from apps.jobs.models import Job
        self.worker = User.objects.create_user(username='w', password='x')
        self.admin = User.objects.create_user(username='a', password='x')
        self.cat = AccountingCategory.objects.create(code='SUP', name='Supplies')
        self.contact = Contact.objects.create(first_name='T', last_name='C', email='r@t.com')
        self.job = Job.objects.create(job_number='JOB-AR1', contact=self.contact)

    def _attach(self, *, amount, material_id, attach_qty=None):
        return ExpenseService.submit(
            entered_by=self.worker, purchased_by=self.worker, amount=amount,
            purchased_on=date(2026, 4, 1), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            material_id=material_id, attach_qty=attach_qty)

    def test_reject_attached_reverses_receipt_and_keeps_provisional_material(self):
        m = MaterialService.create_on_job(
            job=self.job, description='mystery', quantity=Decimal('2'),
            accounting_category=self.cat, units='ea')  # provisional
        e = self._attach(amount=Decimal('30.00'), material_id=m.pk)
        m.refresh_from_db()
        self.assertEqual(m.inventory_item.qty_on_hand, Decimal('2'))
        pli_pk = m.inventory_item_id

        ExpenseService.reject(expense=e, actor=self.admin)

        e.refresh_from_db()
        self.assertEqual(e.status, Expense.STATUS_REJECTED)
        # Material survives — it predates the expense.
        m.refresh_from_db()
        self.assertEqual(m.pk, m.pk)
        self.assertTrue(Material.objects.filter(pk=m.pk).exists())
        # Stock receipt reversed.
        m.inventory_item.refresh_from_db()
        self.assertEqual(m.inventory_item.qty_on_hand, Decimal('0'))
        # EXPENSE provenance cleared (no longer document-confirmed).
        self.assertIsNone(m.cost_source)
        self.assertEqual(m.inventory_item_id, pli_pk)  # lot not un-minted

    def test_reject_partial_attach_reverses_only_received_qty(self):
        m = MaterialService.create_on_job(
            job=self.job, description='ply', quantity=Decimal('12'),
            unit_cost=Decimal('10.00'), accounting_category=self.cat, units='ea')
        m.inventory_item.qty_on_hand = Decimal('8')
        m.inventory_item.save()
        e = self._attach(amount=Decimal('44.00'), material_id=m.pk,
                         attach_qty=Decimal('4'))
        m.refresh_from_db()
        self.assertEqual(m.inventory_item.qty_on_hand, Decimal('12'))

        ExpenseService.reject(expense=e, actor=self.admin)

        m.inventory_item.refresh_from_db()
        self.assertEqual(m.inventory_item.qty_on_hand, Decimal('8'))  # only the 4 backed off
        self.assertTrue(Material.objects.filter(pk=m.pk).exists())


class ExpenseAttachApiTest(TestCase):
    """material_id + attach_qty write-only fields thread through the viewset."""

    def setUp(self):
        _seed_job_config()
        from apps.contacts.models import Contact
        from apps.jobs.models import Job
        self.client_http = Client()
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Supplies', qbo_expense_account_id='500')
        self.user = User.objects.create_user(username='u', password='testpass')
        self.client_http.force_login(self.user)
        self.contact = Contact.objects.create(
            first_name='A', last_name='B', email='a@b.com')
        self.job = Job.objects.create(job_number='JOB-API-AT1', contact=self.contact)

    def test_post_attach_establishes_and_receives(self):
        m = MaterialService.create_on_job(
            job=self.job, description='mystery', quantity=Decimal('2'),
            accounting_category=self.cat, units='ea')
        payload = {
            'amount': '30.00',
            'purchased_on': '2026-04-05',
            'accounting_category': self.cat.pk,
            'payment_method': 'personal',
            'purchased_by': self.user.pk,
            'material_id': m.pk,
        }
        r = self.client_http.post(
            '/api/expenses/', payload, content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        m.refresh_from_db()
        self.assertEqual(m.unit_cost, Decimal('15.00'))
        self.assertEqual(m.cost_source, Material.COST_SOURCE_EXPENSE)
        self.assertEqual(m.inventory_item.qty_on_hand, Decimal('2'))
