"""Pre-approval work: starting a task on a DRAFT / SUBMITTED job.

The pre-approval work feature lets work begin before the job is approved. This
locks in the material/earmark behavior around that:
  - an in-stock PLI material is consumed (QOH drawn) with NO earmark pre-approval
    (the D3 invariant: no reservations until approval);
  - an out-of-stock PLI material blocks the start, and the whole start rolls back
    atomically (no blep, no promotion, QOH untouched);
  - approval (create_earmarks_for_job) does NOT re-earmark a material that was
    already consumed pre-approval.
Freeform (no-PLI) materials are intentionally NOT gated here — they have no stock
concept yet; that's deferred to the freeform-material-procurement spec.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from tests.base import BaseTestCase
from apps.core.models import User, AccountingCategory
from apps.jobs.models import Job, Task, Blep, RateScheme
from apps.jobs.services import TaskLifecycleService
from apps.inventory.models import Material, Earmark, InventoryItem
from apps.inventory.services import InventoryService, MaterialService


class PreApprovalWorkMaterialTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.get(username='admin')
        self.contact = Job.objects.first().contact
        self.cat = (
            AccountingCategory.objects.first()
            or AccountingCategory.objects.create(name='c')
        )

    def _draft_job(self):
        return Job.objects.create(
            job_number=f'JOB-PRE-{timezone.now().timestamp()}',
            contact=self.contact, status=Job.STATUS_DRAFT,
        )

    def _pli(self, code, qoh):
        return InventoryItem.objects.create(
            code=code, accounting_category=self.cat,
            qty_on_hand=Decimal(qoh),
        )

    def test_start_preapproval_consumes_instock_pli_draws_qoh_no_earmark(self):
        job = self._draft_job()
        pli = self._pli('STEEL-IN', '10')
        task = Task(name='Cut', job=job)
        task.stamp_from_scheme(RateScheme.objects.get(pk=1))
        task.save()
        mat = MaterialService.create_on_job(
            job=job, task=task, description='steel',
            quantity=Decimal('3'), inventory_item=pli,
        )

        result = TaskLifecycleService.start_work(task.pk, self.user)

        self.assertIn('blep', result)
        mat.refresh_from_db()
        pli.refresh_from_db()
        self.assertEqual(mat.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)
        self.assertEqual(pli.qty_on_hand, Decimal('7'))  # 10 - 3 drawn down
        self.assertFalse(
            Earmark.objects.filter(inventory_item=pli, job=job).exists()
        )

    def test_start_preapproval_outofstock_pli_blocks_and_rolls_back(self):
        job = self._draft_job()
        pli = self._pli('STEEL-SHORT', '2')
        task = Task(name='Cut', job=job)
        task.stamp_from_scheme(RateScheme.objects.get(pk=1))
        task.save()
        mat = MaterialService.create_on_job(
            job=job, task=task, description='steel',
            quantity=Decimal('5'), inventory_item=pli,
        )

        # The block is now the in-stock check, not the job-status guard.
        with self.assertRaisesRegex(ValidationError, 'on hand'):
            TaskLifecycleService.start_work(task.pk, self.user)

        mat.refresh_from_db()
        pli.refresh_from_db()
        self.assertEqual(mat.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.assertEqual(pli.qty_on_hand, Decimal('2'))  # untouched
        self.assertEqual(
            Task.objects.get(pk=task.pk).status, Task.STATUS_PENDING
        )  # promotion rolled back
        self.assertFalse(Blep.objects.filter(task=task).exists())  # atomic

    def test_create_earmarks_skips_already_consumed_material(self):
        job = self._draft_job()
        pli_consumed = self._pli('C', '10')
        pli_pending = self._pli('P', '10')
        m_consumed = MaterialService.create_on_job(
            job=job, task=None, description='consumed',
            quantity=Decimal('3'), inventory_item=pli_consumed,
        )
        MaterialService.create_on_job(
            job=job, task=None, description='pending',
            quantity=Decimal('4'), inventory_item=pli_pending,
        )
        MaterialService.consume(m_consumed)

        # Approve first — create_earmarks_for_job deliberately no-ops on
        # pre-approval jobs (earmarks belong to committed jobs only), so the
        # consumed-skip behavior under test needs a committed fixture.
        for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
            job.status = s
            job.save()

        # Simulate approval's earmark hook.
        InventoryService.create_earmarks_for_job(job)

        self.assertFalse(
            Earmark.objects.filter(inventory_item=pli_consumed, job=job).exists()
        )
        e = Earmark.objects.get(inventory_item=pli_pending, job=job)
        self.assertEqual(e.quantity, Decimal('4'))
