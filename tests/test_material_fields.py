from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Contact
from apps.jobs.models import Job, Task
from apps.inventory.models import Material, PlanMaterial, InventoryItem, Earmark
from apps.core.models import AccountingCategory
from apps.estimates.models import EstWorksheet
from apps.jobs.models import PlanTask, RateScheme


class MaterialFieldsTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='labor')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(job_number='JOB-TEST-1', contact=self.contact)
        self.scheme = RateScheme.objects.create(
            name='S-mf', algorithm=RateScheme.ENTERED_QTY,
            rate=1, unit_label='ea', accounting_category=self.cat,
        )
        self.task = Task.objects.create(job=self.job, name='t', rate_scheme=self.scheme)

    def test_material_has_job_consumption_state_restocked_qty(self):
        m = Material.objects.create(
            task=self.task, job=self.job,
            description='x', quantity=Decimal('2.00'),
            accounting_category=self.cat,
        )
        self.assertEqual(m.job_id, self.job.pk)
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.assertEqual(m.restocked_qty, Decimal('0.00'))

    def test_non_inventoried_material_defaults_to_pending(self):
        m = Material.objects.create(
            task=self.task, job=self.job,
            description='no-pli', quantity=Decimal('1.00'),
            accounting_category=self.cat,
        )
        self.assertIsNone(m.inventory_item)
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)

    def test_material_rejects_mismatched_task_job(self):
        job_b = Job.objects.create(job_number='JOB-TEST-2', contact=self.contact)
        with self.assertRaises(ValidationError):
            Material.objects.create(
                task=self.task, job=job_b,
                description='x', quantity=Decimal('1.00'),
                accounting_category=self.cat,
            )

    def test_material_rejects_negative_restocked_qty(self):
        m = Material.objects.create(
            task=self.task, job=self.job,
            description='x', quantity=Decimal('2.00'),
            accounting_category=self.cat,
        )
        m.restocked_qty = Decimal('-1.00')
        with self.assertRaises(ValidationError):
            m.save()


class PlanMaterialFieldsTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='plantest@example.com', work_number='555-0200',
        )
        self.job = Job.objects.create(job_number='JOB-PLAN-1', contact=self.contact)
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.pmf_ac = AccountingCategory.objects.create(name='pmf-ac', code='PMF-AC')
        self.pmf_scheme = RateScheme.objects.create(
            name='S-pmf', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('1'), unit_label='ea',
            accounting_category=self.pmf_ac,
        )
        self.pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='pt1',
            rate_scheme=self.pmf_scheme, est_qty=Decimal('1'),
        )

    def test_plan_material_has_est_worksheet(self):
        pm = PlanMaterial.objects.create(
            plan_task=self.pt, est_worksheet=self.ws,
            description='x', quantity=Decimal('1.00'),
            accounting_category=self.pmf_ac,
        )
        self.assertEqual(pm.est_worksheet_id, self.ws.pk)

    def test_plan_material_invariant_rejects_mismatched_ws(self):
        other_job = Job.objects.create(job_number='JOB-PLAN-2', contact=self.contact)
        other_ws = EstWorksheet.objects.create(job=other_job)
        with self.assertRaises(ValidationError):
            PlanMaterial.objects.create(
                plan_task=self.pt, est_worksheet=other_ws,
                description='x', quantity=Decimal('1.00'),
                accounting_category=self.pmf_ac,
            )


class MaterialTaskSetNullTest(TestCase):
    """Gap 1: Material.task on_delete=SET_NULL — deleting a Task must not destroy its Materials."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Null', last_name='Test',
            email='nulltest@example.com',
        )
        self.job = Job.objects.create(job_number='JOB-TSN-1', contact=self.contact)
        cat = AccountingCategory.objects.create(name='tsn-cat', code='TSN1')
        scheme = RateScheme.objects.create(
            name='S-tsn', algorithm=RateScheme.ENTERED_QTY,
            rate=1, unit_label='ea', accounting_category=cat,
        )
        self.task = Task.objects.create(job=self.job, name='deletable', rate_scheme=scheme)

    def test_delete_task_keeps_material_with_null_task_and_original_job(self):
        cat = AccountingCategory.objects.create(name='tsn-mat', code='TSN-MAT')
        m = Material.objects.create(
            task=self.task, job=self.job,
            description='widget', quantity=Decimal('3.00'),
            accounting_category=cat,
        )
        task_pk = self.task.pk
        material_pk = m.pk
        original_job_pk = self.job.pk
        self.task.delete()
        self.assertTrue(Material.objects.filter(pk=material_pk).exists(),
                        'Material row should survive task deletion')
        m.refresh_from_db()
        self.assertIsNone(m.task_id, 'task_id should be NULL after task deleted')
        self.assertEqual(m.job_id, original_job_pk, 'job_id should be unchanged')


class MaterialJobCascadeTest(TestCase):
    """Gap 2: Material.job on_delete=CASCADE — deleting a Job destroys Materials and Earmarks."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='cascade', code='CASC1')
        self.contact = Contact.objects.create(
            first_name='Cascade', last_name='Test',
            email='casctest@example.com',
        )
        self.job = Job.objects.create(job_number='JOB-CASC-1', contact=self.contact)
        self.pli = InventoryItem.objects.create(
            code='CASC-I', accounting_category=self.cat, is_catalog=True,
        )

    def test_delete_job_removes_material_and_earmark(self):
        m = Material.objects.create(
            job=self.job, description='bolt', quantity=Decimal('5.00'),
            inventory_item=self.pli,
            # accounting_category is auto-filled from pli
        )
        Earmark.objects.create(
            inventory_item=self.pli, job=self.job, quantity=Decimal('5.00'),
        )
        material_pk = m.pk
        self.job.delete()
        self.assertFalse(Material.objects.filter(pk=material_pk).exists(),
                         'Material should be cascade-deleted with its Job')
        self.assertFalse(Earmark.objects.filter(
            inventory_item=self.pli).exists(),
            'Earmark should be cascade-deleted with its Job')


class MaterialPropertiesTest(TestCase):
    """Gap 3: is_expense_bound property reflects the expense reverse relation."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='props', code='PROP1')
        self.contact = Contact.objects.create(
            first_name='Prop', last_name='Test',
            email='proptest@example.com',
        )
        self.job = Job.objects.create(job_number='JOB-PROP-1', contact=self.contact)

    def test_is_expense_bound_reflects_expense_reverse_relation(self):
        from apps.expenses.models import Expense
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.create_user('prop_user', password='p')
        m = Material.objects.create(
            job=self.job, description='x', quantity=Decimal('1.00'),
            accounting_category=self.cat,
        )
        self.assertFalse(m.is_expense_bound, 'No expenses yet — should be False')
        Expense.objects.create(
            entered_by=user, amount=Decimal('10'),
            purchased_on='2026-04-14', accounting_category=self.cat,
            payment_method='personal',
            material=m,
        )
        m.refresh_from_db()
        self.assertTrue(m.is_expense_bound, 'After creating Expense — should be True')
