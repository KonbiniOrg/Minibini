"""ChangeOrderAcceptanceService — CO acceptance crystallizes deltas onto Job atoms.

Mirrors EstimateAcceptanceService.on_accept (tests/test_acceptance_plain_lines.py):
- add    → crystallize a new atom via the same discriminator (service_item →
           Task, inventory_item → Material, is_material bare → established
           Material with reverse-markup cost, else → skip: a plain line stays
           document-only, no atom, no source row), source-linked to the CO
           line when an atom is created.
- remove → retire the target line's current atom: cancel a Task (bleps
           preserved), release a pending un-invoiced Material (earmark backed
           out). Consumed / invoiced / terminal atoms and historical
           fee-sourced targets are left alone; document-only targets
           (adjustments, plain lines) are a no-op.
- replace → crystallize the replacement first (a bare CO line mirrors the old
           atom's type), then retire the old atom. A plain (document-only)
           target stays document-only.
Then earmark the job's inventoried materials, exactly like estimate acceptance.
"""
from datetime import timedelta
from decimal import Decimal
from unittest import skip

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.deliverables.models import Deliverable
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import (
    ChangeOrder, ChangeOrderLineItem, ChangeOrderLineItemSource,
    Estimate, EstimateLineItem, EstimateLineItemSource, ServiceItem,
)
from apps.inventory.models import Earmark, InventoryItem, Material
from apps.inventory.services import MaterialService
from apps.jobs.models import Blep, Job, RateScheme, Task


class ChangeOrderAcceptanceBase(TestCase):
    """Shared scaffolding: an approved job with an accepted estimate, put
    on hold so a CO can be authored, sent, and accepted."""

    def setUp(self):
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})

        self.cat = AccountingCategory.objects.create(
            name='Labor', is_active=True, code='LAB')
        self.mat_cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MAT')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-2026-0001',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.service_item = ServiceItem.objects.create(
            template_name='CNC cutting', rate_scheme=self.scheme,
        )
        self.pli = InventoryItem.objects.create(
            code='PLY', accounting_category=self.mat_cat,
            qty_on_hand=Decimal('50'), purchase_price=Decimal('80'),
            selling_price=Decimal('100'), units='ea',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001',
            status=Estimate.STATUS_ACCEPTED,
        )
        Deliverable.objects.create(
            job=self.job, description='Widget', qty_ordered=Decimal('1'),
            units='ea', sort_order=10,
        )

    def _make_co(self):
        self.job.refresh_from_db()
        self.job.on_hold = True
        self.job.hold_reason = 'CO editing'
        self.job.save()
        return ChangeOrderService.create(job_id=self.job.pk)

    def _accept(self, co):
        ChangeOrderService.mark_open(co.pk)
        co = ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_ACCEPTED)
        self.job.refresh_from_db()
        return co

    # --- estimate-side atom-backed lines (as estimate acceptance leaves them) ---

    def _task_backed_line(self, line_number=1, est_qty=Decimal('10')):
        task = Task(
            job=self.job, name='Cutting',
            est_qty=est_qty,
        )
        task.stamp_from_scheme(self.scheme)
        task.save()
        line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=line_number,
            description='Cutting labor', qty=est_qty, price=Decimal('100.00'),
            units='hour', accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=line,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=task.pk,
        )
        return line, task

    def _material_backed_line(self, line_number=1, qty=Decimal('7')):
        material = MaterialService.create_on_job(
            job=self.job, description='Plywood', quantity=qty,
            sell_price=Decimal('100.00'), inventory_item=self.pli,
            accounting_category=self.mat_cat, units='ea',
        )
        line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=line_number,
            description='Plywood', qty=qty, price=Decimal('100.00'),
            units='ea', accounting_category=self.mat_cat,
            inventory_item=self.pli,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=line,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL,
            source_pk=material.pk,
        )
        return line, material


class COAddCrystallizationTests(ChangeOrderAcceptanceBase):
    """Accepted CO `add` lines crystallize atoms via the estimate discriminator."""

    def test_service_add_line_crystallizes_task(self):
        co = self._make_co()
        li = ChangeOrderService.add_line_item_from_service(
            co.pk, self.service_item.pk, Decimal('4'))
        self._accept(co)

        task = Task.objects.get(job=self.job, name='CNC cutting')
        self.assertEqual(task.est_qty, Decimal('4'))
        self.assertEqual(task.source_scheme, self.scheme)
        self.assertEqual(task.status, Task.STATUS_PENDING)
        src = ChangeOrderLineItemSource.objects.get(change_order_line_item=li)
        self.assertEqual(src.source_type, ChangeOrderLineItemSource.SOURCE_TASK)
        self.assertEqual(src.source_pk, task.pk)

    def test_service_add_line_crystallizes_a_schedulable_task(self):
        """Task 8: self.scheme is unit_label='hour' (setUp) and the CO line
        only carries qty — generate_task's pair-fill must derive
        est_worker_time so CO-accepted tasks are schedulable too."""
        co = self._make_co()
        ChangeOrderService.add_line_item_from_service(
            co.pk, self.service_item.pk, Decimal('4'))
        self._accept(co)

        task = Task.objects.get(job=self.job, name='CNC cutting')
        self.assertEqual(task.est_qty, Decimal('4'))
        self.assertEqual(task.est_worker_time, timedelta(hours=4))

    def test_inventory_add_line_crystallizes_material_and_earmarks(self):
        co = self._make_co()
        li = ChangeOrderService.add_line_item_from_pli(co.pk, self.pli.pk, Decimal('5'))
        self._accept(co)

        mat = Material.objects.get(job=self.job, inventory_item=self.pli)
        self.assertEqual(mat.quantity, Decimal('5'))
        self.assertEqual(mat.sell_price, Decimal('100.00'))
        src = ChangeOrderLineItemSource.objects.get(change_order_line_item=li)
        self.assertEqual(src.source_type, ChangeOrderLineItemSource.SOURCE_MATERIAL)
        self.assertEqual(src.source_pk, mat.pk)
        earmark = Earmark.objects.get(job=self.job, inventory_item=self.pli)
        self.assertEqual(earmark.quantity, Decimal('5'))

    def test_bare_material_add_line_establishes_with_reverse_markup(self):
        # Parity with estimate acceptance: a bare is_material CO line is
        # ESTABLISHED at acceptance — placeholder cost backed out of the locked
        # sell (sell / (1 + markup%)), QOH-0 lot, cost_source='estimated' —
        # not left provisional.
        Configuration.objects.create(
            key='default_material_markup_percent', value='25')
        co = self._make_co()
        li = ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='Dragon skin', qty=Decimal('2'), price=Decimal('400.00'),
            units='sheet', is_material=True, accounting_category=self.mat_cat.pk,
        )
        self._accept(co)

        mat = Material.objects.get(job=self.job, description='Dragon skin')
        self.assertIsNotNone(mat.inventory_item)
        self.assertEqual(mat.cost_source, Material.COST_SOURCE_ESTIMATED)
        self.assertEqual(mat.unit_cost, Decimal('320.00'))   # 400 / 1.25
        self.assertEqual(mat.sell_price, Decimal('400.00'))  # locked sell, never re-derived
        self.assertEqual(mat.inventory_item.qty_on_hand, Decimal('0'))
        self.assertEqual(mat.quantity, Decimal('2'))
        src = ChangeOrderLineItemSource.objects.get(change_order_line_item=li)
        self.assertEqual(src.source_type, ChangeOrderLineItemSource.SOURCE_MATERIAL)
        self.assertEqual(src.source_pk, mat.pk)

    def test_bare_add_line_stays_document_only(self):
        # A plain add line (no service_item, no inventory_item, not
        # is_material) crystallizes NOTHING: no atom, no source row — it
        # stays a document-only line.
        co = self._make_co()
        li = ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra scope', qty=Decimal('3'), price=Decimal('25.00'),
            accounting_category=self.cat.pk,
        )
        self._accept(co)

        self.assertEqual(Task.objects.filter(job=self.job).count(), 0)
        self.assertEqual(Material.objects.filter(job=self.job).count(), 0)
        self.assertFalse(
            ChangeOrderLineItemSource.objects.filter(
                change_order_line_item=li).exists())
        self.assertEqual(Task.objects.filter(job=self.job).count(), 0)
        self.assertEqual(Material.objects.filter(job=self.job).count(), 0)
        # The line itself is untouched — still present on the document.
        li.refresh_from_db()
        self.assertEqual(li.description, 'Extra scope')
        self.assertEqual(li.qty, Decimal('3'))
        self.assertEqual(li.price, Decimal('25.00'))
        co.refresh_from_db()
        self.assertEqual(co.status, ChangeOrder.STATUS_ACCEPTED)

    def test_bare_add_line_without_ac_blocks_send(self):
        co = self._make_co()
        ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
            description='No category', qty=Decimal('1'), price=Decimal('10.00'),
        )
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.mark_open(co.pk)
        self.assertIn('accounting category', str(ctx.exception).lower())

    def test_on_accept_is_idempotent(self):
        from apps.estimates.co_acceptance import ChangeOrderAcceptanceService
        co = self._make_co()
        ChangeOrderService.add_line_item_from_service(
            co.pk, self.service_item.pk, Decimal('4'))
        self._accept(co)
        # Re-running acceptance must not duplicate atoms: crystallized lines
        # already carry a source row and are skipped.
        ChangeOrderAcceptanceService.on_accept(co)
        self.assertEqual(
            Task.objects.filter(job=self.job, name='CNC cutting').count(), 1)


class CORemoveCrystallizationTests(ChangeOrderAcceptanceBase):
    """Accepted CO `remove` lines retire the target line's current atom."""

    def _remove_line(self, co, target):
        return ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_REMOVE,
            target_line_item=target.pk,
        )

    def test_remove_task_line_cancels_task_and_preserves_bleps(self):
        line, task = self._task_backed_line()
        worker = User.objects.create(username='worker')
        now = timezone.now()
        blep = Blep.objects.create(
            user=worker, task=task, start_time=now, end_time=now,
        )
        co = self._make_co()
        self._remove_line(co, line)
        self._accept(co)

        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_CANCELLED)
        self.assertTrue(Blep.objects.filter(pk=blep.pk).exists())

    def test_remove_complete_task_is_left_alone(self):
        line, task = self._task_backed_line()
        Task.objects.filter(pk=task.pk).update(status=Task.STATUS_COMPLETE)
        co = self._make_co()
        self._remove_line(co, line)
        self._accept(co)

        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_COMPLETE)

    def test_remove_material_line_releases_material_and_earmark(self):
        line, material = self._material_backed_line()
        self.assertEqual(
            Earmark.objects.get(job=self.job, inventory_item=self.pli).quantity,
            Decimal('7'))
        co = self._make_co()
        self._remove_line(co, line)
        self._accept(co)

        # A CO target is by definition claimed → released, not deleted: the
        # quantity moves to released_qty and the claim stays resolvable history.
        material.refresh_from_db()
        self.assertEqual(
            material.consumption_state, Material.CONSUMPTION_STATE_RELEASED)
        self.assertEqual(material.quantity, Decimal('0'))
        self.assertEqual(material.released_qty, Decimal('7'))
        self.assertFalse(
            Earmark.objects.filter(job=self.job, inventory_item=self.pli).exists())
        self.assertEqual(line.sources.get().resolve().pk, material.pk)

    def test_remove_consumed_material_is_left_alone(self):
        line, material = self._material_backed_line()
        MaterialService.consume(material)
        co = self._make_co()
        self._remove_line(co, line)
        self._accept(co)

        material.refresh_from_db()
        self.assertEqual(
            material.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)

    def test_remove_adjustment_line_is_document_only(self):
        adj_scheme = RateScheme.objects.create(
            name='Rush 10%', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='none', accounting_category=self.cat,
        )
        line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Rush surcharge',
            qty=Decimal('1'), price=Decimal('50.00'), accounting_category=self.cat,
            adjustment_service=adj_scheme,
        )
        co = self._make_co()
        self._remove_line(co, line)
        self._accept(co)  # must not raise; nothing to retire

        co.refresh_from_db()
        self.assertEqual(co.status, ChangeOrder.STATUS_ACCEPTED)


class COReplaceCrystallizationTests(ChangeOrderAcceptanceBase):
    """Accepted CO `replace` lines retire the old atom and crystallize its
    replacement. A bare CO line mirrors the old atom's type."""

    def _replace_line(self, co, target, **fields):
        defaults = dict(
            action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=target.pk,
        )
        defaults.update(fields)
        return ChangeOrderService.add_line_item(co.pk, **defaults)

    def test_replace_task_line_cancels_old_and_mirrors_new_task(self):
        line, old_task = self._task_backed_line(est_qty=Decimal('10'))
        co = self._make_co()
        li = self._replace_line(
            co, line, description='Cutting labor (more)', qty=Decimal('15'),
            price=Decimal('100.00'), units='hour',
        )
        self._accept(co)

        old_task.refresh_from_db()
        self.assertEqual(old_task.status, Task.STATUS_CANCELLED)
        src = ChangeOrderLineItemSource.objects.get(change_order_line_item=li)
        self.assertEqual(src.source_type, ChangeOrderLineItemSource.SOURCE_TASK)
        new_task = Task.objects.get(pk=src.source_pk)
        self.assertEqual(new_task.est_qty, Decimal('15'))
        # A bare replace line mirrors the old task's money via copy_fields()
        # (task-owned-money Phase 1): rate/qty_source/unit_label/AC/modifiers
        # carry over, but source_scheme is document provenance and is NOT
        # copied — the mirrored task is a fresh document occurrence (same as
        # JobService.duplicate_job's _copy_work_to_job; see test_copy_fields.py).
        self.assertIsNone(new_task.source_scheme)
        self.assertEqual(new_task.rate, old_task.rate)
        self.assertEqual(new_task.qty_source, old_task.qty_source)
        self.assertEqual(new_task.unit_label, old_task.unit_label)
        self.assertEqual(new_task.accounting_category_id, old_task.accounting_category_id)
        self.assertEqual(new_task.name, old_task.name)
        self.assertEqual(new_task.description, 'Cutting labor (more)')
        self.assertEqual(new_task.status, Task.STATUS_PENDING)

    def test_replace_material_line_inherits_inventory_item(self):
        line, old_material = self._material_backed_line(qty=Decimal('7'))
        co = self._make_co()
        li = self._replace_line(
            co, line, description='Plywood', qty=Decimal('4'),
            price=Decimal('110.00'), units='ea',
        )
        self._accept(co)

        old_material.refresh_from_db()
        self.assertEqual(
            old_material.consumption_state, Material.CONSUMPTION_STATE_RELEASED)
        src = ChangeOrderLineItemSource.objects.get(change_order_line_item=li)
        self.assertEqual(src.source_type, ChangeOrderLineItemSource.SOURCE_MATERIAL)
        new_mat = Material.objects.get(pk=src.source_pk)
        self.assertEqual(new_mat.inventory_item, self.pli)
        self.assertEqual(new_mat.quantity, Decimal('4'))
        self.assertEqual(new_mat.sell_price, Decimal('110.00'))
        earmark = Earmark.objects.get(job=self.job, inventory_item=self.pli)
        self.assertEqual(earmark.quantity, Decimal('4'))

    def test_bare_replace_of_provisional_material_establishes_replacement(self):
        # A pre-parity CO could leave a crystallized material provisional; a
        # bare replace mirrors its inventory_item (None). The replacement must
        # still be born established — no material is born provisional from a
        # document.
        provisional = MaterialService.create_on_job(
            job=self.job, description='Foam', quantity=Decimal('3'),
            sell_price=Decimal('100.00'), inventory_item=None,
            accounting_category=self.mat_cat, units='sheet',
        )
        line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1,
            description='Foam', qty=Decimal('3'), price=Decimal('100.00'),
            units='sheet', accounting_category=self.mat_cat, is_material=True,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=line,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL,
            source_pk=provisional.pk,
        )
        co = self._make_co()
        li = self._replace_line(
            co, line, description='Foam v2', qty=Decimal('2'),
            price=Decimal('120.00'), units='sheet',
        )
        self._accept(co)

        src = ChangeOrderLineItemSource.objects.get(change_order_line_item=li)
        new_mat = Material.objects.get(pk=src.source_pk)
        self.assertIsNotNone(new_mat.inventory_item)
        self.assertEqual(new_mat.cost_source, Material.COST_SOURCE_ESTIMATED)
        self.assertEqual(new_mat.sell_price, Decimal('120.00'))

    def test_replace_plain_line_stays_document_only(self):
        # A plain estimate line (no source rows — post-narrowing acceptance
        # left it document-only) replaced by a bare CO line: the delta stays
        # document-level. No atom is created, no source row is written.
        line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1,
            description='Rush handling', qty=Decimal('1'), price=Decimal('75.00'),
            accounting_category=self.cat,
        )
        co = self._make_co()
        li = self._replace_line(
            co, line, description='Rush handling (expanded)', qty=Decimal('2'),
            price=Decimal('90.00'), accounting_category=self.cat.pk,
        )
        self._accept(co)

        self.assertEqual(Task.objects.filter(job=self.job).count(), 0)
        self.assertEqual(Material.objects.filter(job=self.job).count(), 0)
        self.assertFalse(
            ChangeOrderLineItemSource.objects.filter(
                change_order_line_item=li).exists())
        co.refresh_from_db()
        self.assertEqual(co.status, ChangeOrder.STATUS_ACCEPTED)

    @skip(
        'rewritten in Task 3 — replace is commercial-only now (CO '
        'amend-in-place Task 1 clean() rule forbids is_material/'
        'service_item/inventory_item on a replace line); typed-descriptor '
        'replace crystallization is replaced by remove+add in Task 3'
    )
    def test_typed_replace_crystallizes_per_descriptor_not_mirror(self):
        # A TYPED replace (own descriptor: is_material here) targeting a
        # task-backed estimate line must never resolve the target's mirror —
        # the descriptor wins, so acceptance crystallizes a Material per the
        # descriptor while the old task is retired as usual.
        Configuration.objects.get_or_create(
            key='default_material_markup_percent', defaults={'value': '25'})
        line, old_task = self._task_backed_line(est_qty=Decimal('10'))
        co = self._make_co()
        li = self._replace_line(
            co, line, description='Cutting as material', qty=Decimal('2'),
            price=Decimal('90.00'), units='ea', is_material=True,
            accounting_category=self.mat_cat.pk,
        )
        self._accept(co)  # must not raise

        src = ChangeOrderLineItemSource.objects.get(change_order_line_item=li)
        self.assertEqual(src.source_type, ChangeOrderLineItemSource.SOURCE_MATERIAL)
        mat = Material.objects.get(pk=src.source_pk)
        self.assertEqual(mat.quantity, Decimal('2'))
        old_task.refresh_from_db()
        self.assertEqual(old_task.status, Task.STATUS_CANCELLED)
        co.refresh_from_db()
        self.assertEqual(co.status, ChangeOrder.STATUS_ACCEPTED)

    def test_mirror_of_unknown_source_type_raises(self):
        # The mirror dispatch is explicit: task and material only. Any other
        # source_type (a future atom kind) must raise, never silently
        # mistype the replacement.
        from apps.estimates.co_acceptance import ChangeOrderAcceptanceService
        with self.assertRaises(ValueError) as ctx:
            ChangeOrderAcceptanceService._mirror_of([('gizmo', object())])
        self.assertIn('gizmo', str(ctx.exception))

    def test_second_co_replace_resolves_through_first_replacement(self):
        line, original_task = self._task_backed_line(est_qty=Decimal('10'))
        co1 = self._make_co()
        li1 = self._replace_line(
            co1, line, description='Cutting v2', qty=Decimal('15'),
            price=Decimal('100.00'), units='hour',
        )
        self._accept(co1)
        src1 = ChangeOrderLineItemSource.objects.get(change_order_line_item=li1)
        co1_task = Task.objects.get(pk=src1.source_pk)

        # Job went back to approved; hold it again for CO2.
        co2 = self._make_co()
        li2 = self._replace_line(
            co2, line, description='Cutting v3', qty=Decimal('20'),
            price=Decimal('100.00'), units='hour',
        )
        self._accept(co2)

        co1_task.refresh_from_db()
        self.assertEqual(co1_task.status, Task.STATUS_CANCELLED)
        src2 = ChangeOrderLineItemSource.objects.get(change_order_line_item=li2)
        new_task = Task.objects.get(pk=src2.source_pk)
        self.assertEqual(new_task.est_qty, Decimal('20'))

    def test_adds_crystallize_before_removes(self):
        """A CO that removes the job's only task while adding a new one must
        not let the cancel-side auto-advance the job to work_complete."""
        line, old_task = self._task_backed_line()
        co = self._make_co()
        ChangeOrderService.add_line_item_from_service(
            co.pk, self.service_item.pk, Decimal('6'))
        ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_REMOVE,
            target_line_item=line.pk,
        )
        self._accept(co)

        old_task.refresh_from_db()
        self.assertEqual(old_task.status, Task.STATUS_CANCELLED)
        self.assertTrue(
            Task.objects.filter(job=self.job, status=Task.STATUS_PENDING).exists())
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)


class COAuthoringParityTests(ChangeOrderAcceptanceBase):
    """Part A: CO line authoring mirrors the estimate's service pick and
    is_material marker rules."""

    def test_add_line_item_from_service_snapshots_service_values(self):
        co = self._make_co()
        li = ChangeOrderService.add_line_item_from_service(
            co.pk, self.service_item.pk, Decimal('4'))

        self.assertEqual(li.action, ChangeOrderLineItem.ACTION_ADD)
        self.assertEqual(li.service_item, self.service_item)
        self.assertEqual(li.description, 'CNC cutting')
        self.assertEqual(li.qty, Decimal('4'))
        self.assertEqual(li.units, 'hour')
        self.assertEqual(li.price, Decimal('100'))
        self.assertEqual(li.accounting_category, self.cat)

    def test_is_material_line_defaults_ac_from_config(self):
        Configuration.objects.create(
            key='default_material_accounting_category', value=str(self.mat_cat.pk))
        co = self._make_co()
        li = ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='Mystery membrane', qty=Decimal('1'),
            price=Decimal('200.00'), is_material=True,
        )
        self.assertEqual(li.accounting_category, self.mat_cat)

    def test_is_material_invalid_with_inventory_item(self):
        co = self._make_co()
        with self.assertRaises(ValidationError):
            ChangeOrderService.add_line_item(
                co.pk, action=ChangeOrderLineItem.ACTION_ADD,
                description='PLY', qty=Decimal('1'), price=Decimal('100.00'),
                inventory_item=self.pli.pk, is_material=True,
            )

    def test_seed_new_copies_crystallization_fields(self):
        co = self._make_co()
        ChangeOrderService.add_line_item_from_service(
            co.pk, self.service_item.pk, Decimal('4'))
        ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='Membrane', qty=Decimal('1'), price=Decimal('50.00'),
            is_material=True, accounting_category=self.mat_cat.pk,
        )
        ChangeOrderService.mark_open(co.pk)
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_REJECTED)
        new_co = ChangeOrderService.seed_new(co.pk)

        svc_copy = ChangeOrderLineItem.objects.get(
            change_order=new_co, description='CNC cutting')
        self.assertEqual(svc_copy.service_item, self.service_item)
        mat_copy = ChangeOrderLineItem.objects.get(
            change_order=new_co, description='Membrane')
        self.assertTrue(mat_copy.is_material)
        self.assertEqual(mat_copy.accounting_category, self.mat_cat)


class COAgreementBillingTests(ChangeOrderAcceptanceBase):
    """The agreement still carries CO document lines (no atom behind them).
    The source_fee_id agreement channel is gone: line dicts carry no such
    key."""

    def test_compose_agreement_includes_co_add_line_without_fee(self):
        # A plain CO add line rides the agreement as a document line; the
        # line dict no longer carries a source_fee_id key at all.
        from apps.estimates.agreement import compose_agreement
        co = self._make_co()
        ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra scope', qty=Decimal('1'), price=Decimal('10.00'),
            accounting_category=self.cat.pk,
        )
        self._accept(co)

        agreement = compose_agreement(self.job)
        co_lines = [l for l in agreement['lines'] if l['origin'] == 'change_order']
        self.assertEqual(len(co_lines), 1)
        self.assertNotIn('source_fee_id', co_lines[0])
