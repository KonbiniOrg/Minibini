"""ChangeOrderAcceptanceService — CO acceptance crystallizes deltas onto Job atoms.

Mirrors EstimateAcceptanceService.on_accept (tests/test_acceptance_plain_lines.py):
- add    → crystallize a new atom via the same discriminator (service_item →
           Task, inventory_item → Material, is_material bare → established
           Material with reverse-markup cost, else → skip: a plain line stays
           document-only, no atom, no source row), source-linked to the CO
           line when an atom is created.
- remove → stamp `descoped_by = co` on the target's current atom(s), then
           retire: cancel a Task (bleps preserved), release a pending
           un-invoiced Material (earmark backed out). Consumed / invoiced /
           terminal atoms are still stamped but otherwise left alone (the
           stamp is descope provenance, not a retirement outcome);
           document-only targets (adjustments, plain lines) are a no-op.
- replace → backing inheritance: the target's current claim rows move onto
           the replacement CO line. Nothing is crystallized, nothing is
           retired — the underlying Task/Material is untouched (same pk,
           same status). A plain (document-only) target stays document-only.
Then earmark the job's inventoried materials, exactly like estimate acceptance.
"""
from datetime import timedelta
from decimal import Decimal

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
        Configuration.objects.create(
            key='default_material_accounting_category', value=str(self.mat_cat.pk))
        co = self._make_co()
        # Choosing the Materials AC is what makes this a material line
        # (is_material derives server-side; the checkbox is retired).
        li = ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='Dragon skin', qty=Decimal('2'), price=Decimal('400.00'),
            units='sheet', accounting_category=self.mat_cat.pk,
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
        co = self._accept(co)

        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_CANCELLED)
        self.assertTrue(Blep.objects.filter(pk=blep.pk).exists())
        # Stored descope provenance — stamped regardless of the retirement
        # outcome, and what the invoice pool's badge reads.
        self.assertEqual(task.descoped_by_id, co.pk)

    def test_remove_complete_task_is_left_alone_but_stamped(self):
        line, task = self._task_backed_line()
        Task.objects.filter(pk=task.pk).update(status=Task.STATUS_COMPLETE)
        co = self._make_co()
        self._remove_line(co, line)
        co = self._accept(co)

        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_COMPLETE)
        self.assertEqual(task.descoped_by_id, co.pk)

    def test_remove_material_line_releases_material_and_earmark(self):
        line, material = self._material_backed_line()
        self.assertEqual(
            Earmark.objects.get(job=self.job, inventory_item=self.pli).quantity,
            Decimal('7'))
        co = self._make_co()
        self._remove_line(co, line)
        co = self._accept(co)

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
        self.assertEqual(material.descoped_by_id, co.pk)

    def test_remove_consumed_material_is_left_alone_but_stamped(self):
        line, material = self._material_backed_line()
        MaterialService.consume(material)
        co = self._make_co()
        self._remove_line(co, line)
        co = self._accept(co)

        material.refresh_from_db()
        self.assertEqual(
            material.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)
        self.assertEqual(material.descoped_by_id, co.pk)

    def test_remove_invoiced_material_is_left_alone_but_stamped(self):
        from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
        line, material = self._material_backed_line()
        inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        inv_li = InvoiceLineItem.objects.create(
            invoice=inv, description='Plywood', qty=material.quantity,
            units='ea', price=material.sell_price,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=inv_li,
            source_type=InvoiceLineItemSource.SOURCE_MATERIAL,
            source_pk=material.pk,
        )
        co = self._make_co()
        self._remove_line(co, line)
        co = self._accept(co)

        material.refresh_from_db()
        # Billed reality is not unwound by a document — left pending.
        self.assertEqual(
            material.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.assertEqual(material.descoped_by_id, co.pk)

    def test_remove_then_readd_atom_on_same_co_is_not_retired(self):
        # RM 2026-08-10: removing a line frees its atoms into the CO pool, so
        # the same CO can re-claim one on an add line ("restate the work under
        # new terms"). Acceptance must then carry the work forward — no
        # cancel, no descope stamp — instead of retiring it out from under
        # the add line it now backs.
        line, task = self._task_backed_line()
        co = self._make_co()
        self._remove_line(co, line)
        add_li = ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
            line_number=2, description='Cutting, rescoped',
            qty=Decimal('10'), price=Decimal('120.00'),
            accounting_category=self.cat,
        )
        ChangeOrderLineItemSource.objects.create(
            change_order_line_item=add_li,
            source_type=ChangeOrderLineItemSource.SOURCE_TASK,
            source_pk=task.pk,
        )
        co = self._accept(co)

        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_PENDING)
        self.assertIsNone(task.descoped_by_id)
        # The authored claim survives untouched — nothing re-crystallized.
        self.assertEqual(add_li.sources.get().resolve().pk, task.pk)

    def test_remove_then_readd_material_on_same_co_is_not_released(self):
        line, material = self._material_backed_line()
        co = self._make_co()
        self._remove_line(co, line)
        add_li = ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
            line_number=2, description='Plywood, rescoped',
            qty=Decimal('7'), price=Decimal('110.00'),
            accounting_category=self.mat_cat,
        )
        ChangeOrderLineItemSource.objects.create(
            change_order_line_item=add_li,
            source_type=ChangeOrderLineItemSource.SOURCE_MATERIAL,
            source_pk=material.pk,
        )
        co = self._accept(co)

        material.refresh_from_db()
        self.assertEqual(
            material.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.assertEqual(material.quantity, Decimal('7'))
        self.assertIsNone(material.descoped_by_id)
        self.assertTrue(
            Earmark.objects.filter(job=self.job, inventory_item=self.pli).exists())

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
    """Accepted CO `replace` lines are backing inheritance (spec §9.3 / §11
    #1): the target's current claim rows move onto the replacement CO line.
    Nothing is crystallized, nothing is retired — the underlying Task/
    Material is completely untouched (same pk, same status, never
    cancelled)."""

    def _replace_line(self, co, target, **fields):
        defaults = dict(
            action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=target.pk,
        )
        defaults.update(fields)
        return ChangeOrderService.add_line_item(co.pk, **defaults)

    def test_replace_task_line_moves_claim_not_crystallize(self):
        from apps.estimates.co_acceptance import ChangeOrderAcceptanceService
        line, task = self._task_backed_line(est_qty=Decimal('10'))
        co = self._make_co()
        li = self._replace_line(
            co, line, description='Cutting labor (more)', qty=Decimal('15'),
            price=Decimal('100.00'), units='hour',
        )
        counts = ChangeOrderAcceptanceService.on_accept(co)

        self.assertEqual(counts, {
            'tasks_created': 0, 'materials_created': 0,
            'tasks_cancelled': 0, 'materials_removed': 0,
        })
        # The target's claim row is gone…
        self.assertFalse(line.sources.exists())
        # …and an identical claim row now lives on the replacement CO line.
        src = ChangeOrderLineItemSource.objects.get(change_order_line_item=li)
        self.assertEqual(src.source_type, ChangeOrderLineItemSource.SOURCE_TASK)
        self.assertEqual(src.source_pk, task.pk)
        # The task itself: same pk, same status, NOT cancelled — the CO line
        # only re-prices/re-describes the work, it doesn't touch the atom.
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_PENDING)
        self.assertIsNone(task.descoped_by_id)
        self.assertEqual(task.est_qty, Decimal('10'))  # unchanged by the CO's qty=15

    def test_replace_material_line_moves_claim_not_crystallize(self):
        from apps.estimates.co_acceptance import ChangeOrderAcceptanceService
        line, material = self._material_backed_line(qty=Decimal('7'))
        earmark_before = Earmark.objects.get(job=self.job, inventory_item=self.pli).quantity
        co = self._make_co()
        li = self._replace_line(
            co, line, description='Plywood (more)', qty=Decimal('4'),
            price=Decimal('110.00'), units='ea',
        )
        counts = ChangeOrderAcceptanceService.on_accept(co)

        self.assertEqual(counts, {
            'tasks_created': 0, 'materials_created': 0,
            'tasks_cancelled': 0, 'materials_removed': 0,
        })
        self.assertFalse(line.sources.exists())
        src = ChangeOrderLineItemSource.objects.get(change_order_line_item=li)
        self.assertEqual(src.source_type, ChangeOrderLineItemSource.SOURCE_MATERIAL)
        self.assertEqual(src.source_pk, material.pk)
        material.refresh_from_db()
        self.assertEqual(
            material.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.assertIsNone(material.descoped_by_id)
        self.assertEqual(material.quantity, Decimal('7'))  # unchanged by the CO's qty=4
        # Untouched atom → untouched earmark (no re-crystallization to earmark).
        self.assertEqual(
            Earmark.objects.get(job=self.job, inventory_item=self.pli).quantity,
            earmark_before)

    def test_replace_plain_line_stays_document_only(self):
        # A plain estimate line (no source rows — post-narrowing acceptance
        # left it document-only) replaced by a bare CO line: the delta stays
        # document-level. No claim row to move, so the CO line stays sourceless.
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

    def test_replace_is_idempotent_on_rerun(self):
        from apps.estimates.co_acceptance import ChangeOrderAcceptanceService
        line, task = self._task_backed_line(est_qty=Decimal('10'))
        co = self._make_co()
        li = self._replace_line(
            co, line, description='Cutting labor (more)', qty=Decimal('15'),
            price=Decimal('100.00'), units='hour',
        )
        self._accept(co)
        self.assertEqual(
            ChangeOrderLineItemSource.objects.filter(change_order_line_item=li).count(), 1)

        # Re-running acceptance must not move the (already-moved) claim again
        # or duplicate the source row — the line already has sources, so the
        # replace loop skips it outright.
        counts = ChangeOrderAcceptanceService.on_accept(co)

        self.assertEqual(counts, {
            'tasks_created': 0, 'materials_created': 0,
            'tasks_cancelled': 0, 'materials_removed': 0,
        })
        self.assertEqual(
            ChangeOrderLineItemSource.objects.filter(change_order_line_item=li).count(), 1)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_PENDING)

    def test_second_co_replace_resolves_through_first_replacement(self):
        line, task = self._task_backed_line(est_qty=Decimal('10'))
        co1 = self._make_co()
        li1 = self._replace_line(
            co1, line, description='Cutting v2', qty=Decimal('15'),
            price=Decimal('100.00'), units='hour',
        )
        self._accept(co1)
        src1 = ChangeOrderLineItemSource.objects.get(change_order_line_item=li1)
        self.assertEqual(src1.source_pk, task.pk)

        # Job went back to approved; hold it again for CO2, also targeting
        # the original estimate line — the claim now lives on li1, not on
        # the estimate line, so CO2 must chain through li1 to find it.
        co2 = self._make_co()
        li2 = self._replace_line(
            co2, line, description='Cutting v3', qty=Decimal('20'),
            price=Decimal('100.00'), units='hour',
        )
        self._accept(co2)

        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_PENDING)  # never touched
        self.assertIsNone(task.descoped_by_id)
        # li1 handed its claim row off to li2 — it no longer carries one.
        self.assertFalse(
            ChangeOrderLineItemSource.objects.filter(change_order_line_item=li1).exists())
        src2 = ChangeOrderLineItemSource.objects.get(change_order_line_item=li2)
        self.assertEqual(src2.source_pk, task.pk)

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


class ChecklistAnsweredByAcceptedCOTests(ChangeOrderAcceptanceBase):
    """Finding 1 (final review, CRITICAL — chain-aware answeredness):
    EstimateService.unanswered_lines / EstimateLineItemSerializer.
    needs_work_decision must count a line answered once an accepted CO's
    replace or remove line targets it — even though `_move_claims_to`
    moves (replace) or never creates (remove) an EstimateLineItemSource row
    on the original estimate line itself. Before this fix: a replaced hand
    line showed phantom mint/decline affordances and could double-mint; a
    replaced catalog line silently blocked auto-release forever (no UI
    path to answer it, since it carries no plain-hand-line escape hatch)."""

    def _replace_line(self, co, target, **fields):
        defaults = dict(
            action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=target.pk,
        )
        defaults.update(fields)
        return ChangeOrderService.add_line_item(co.pk, **defaults)

    def test_replace_accepted_plain_hand_line_no_longer_unanswered(self):
        from apps.api.estimates.serializers import EstimateLineItemSerializer
        from apps.estimates.services import EstimateService

        line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Rush handling',
            qty=Decimal('1'), price=Decimal('75.00'), accounting_category=self.cat,
        )
        co = self._make_co()
        self._replace_line(
            co, line, description='Rush handling (expanded)', qty=Decimal('2'),
            price=Decimal('90.00'), accounting_category=self.cat.pk,
        )
        self._accept(co)

        self.assertNotIn(line, list(EstimateService.unanswered_lines(self.estimate)))
        self.assertFalse(EstimateLineItemSerializer(line).data['needs_work_decision'])

    def test_replace_accepted_catalog_line_doesnt_block_auto_release(self):
        """A catalog (service_item-backed) line, sourced exactly as estimate
        acceptance leaves it, replaced by an accepted CO — its OWN source
        row moves off (backing inheritance), which used to be its only
        answered signal. A second, still-unanswered plain hand line proves
        the job releases once THAT line is answered — the replaced catalog
        line was never really blocking it."""
        from apps.estimates.services import EstimateService

        task = Task(job=self.job, name='CNC cutting', est_qty=Decimal('4'))
        task.stamp_from_scheme(self.scheme)
        task.save()
        catalog_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='CNC cutting',
            qty=Decimal('4'), price=Decimal('400.00'), units='hour',
            accounting_category=self.cat, service_item=self.service_item,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=catalog_line,
            source_type=EstimateLineItemSource.SOURCE_TASK, source_pk=task.pk,
        )
        other_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='Plain hand line',
            qty=Decimal('1'), price=Decimal('50.00'), accounting_category=self.cat,
        )

        co = self._make_co()
        self._replace_line(
            co, catalog_line, description='CNC cutting (more)', qty=Decimal('6'),
            price=Decimal('600.00'), units='hour', accounting_category=self.cat.pk,
        )
        self._accept(co)

        # The catalog line lost its own source row (moved to the CO line)…
        self.assertFalse(catalog_line.sources.exists())
        # …but must NOT reappear as unanswered.
        unanswered = list(EstimateService.unanswered_lines(self.estimate))
        self.assertNotIn(catalog_line, unanswered)
        self.assertIn(other_line, unanswered)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)  # other_line still unanswered

        # Answer the OTHER line — the job releases; the replaced catalog
        # line was never the thing blocking it.
        EstimateService.update_line_item(other_line.pk, work_declined=True)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)

    def test_decline_last_then_replace_ordering(self):
        """Answering order must not matter: decline the last unanswered
        line FIRST (before any CO exists) — the job releases. THEN author
        + accept a replace CO against the already-answered (source-backed)
        line: the checklist must stay satisfied and the job must not
        un-release."""
        from apps.estimates.services import EstimateService

        task = Task(job=self.job, name='CNC cutting', est_qty=Decimal('4'))
        task.stamp_from_scheme(self.scheme)
        task.save()
        catalog_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='CNC cutting',
            qty=Decimal('4'), price=Decimal('400.00'), units='hour',
            accounting_category=self.cat, service_item=self.service_item,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=catalog_line,
            source_type=EstimateLineItemSource.SOURCE_TASK, source_pk=task.pk,
        )
        other_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='Plain hand line',
            qty=Decimal('1'), price=Decimal('50.00'), accounting_category=self.cat,
        )

        EstimateService.update_line_item(other_line.pk, work_declined=True)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)

        co = self._make_co()
        self._replace_line(
            co, catalog_line, description='CNC cutting (more)', qty=Decimal('6'),
            price=Decimal('600.00'), units='hour', accounting_category=self.cat.pk,
        )
        self._accept(co)

        self.assertFalse(EstimateService.unanswered_lines(self.estimate).exists())
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)

    def test_remove_targeted_plain_line_is_answered(self):
        from apps.api.estimates.serializers import EstimateLineItemSerializer
        from apps.estimates.services import EstimateService

        line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Skip this',
            qty=Decimal('1'), price=Decimal('40.00'), accounting_category=self.cat,
        )
        co = self._make_co()
        ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_REMOVE, target_line_item=line.pk,
        )
        self._accept(co)

        self.assertNotIn(line, list(EstimateService.unanswered_lines(self.estimate)))
        self.assertFalse(EstimateLineItemSerializer(line).data['needs_work_decision'])


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

    def test_is_material_derives_from_the_materials_ac(self):
        # RM 2026-08-11: the checkbox is retired — a bare add line IS a
        # material exactly when its AC is the configured Materials AC.
        Configuration.objects.create(
            key='default_material_accounting_category', value=str(self.mat_cat.pk))
        co = self._make_co()
        li = ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='Mystery membrane', qty=Decimal('1'),
            price=Decimal('200.00'), accounting_category=self.mat_cat.pk,
        )
        self.assertTrue(li.is_material)
        other = ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='Rush', qty=Decimal('1'),
            price=Decimal('50.00'), accounting_category=self.cat.pk,
        )
        self.assertFalse(other.is_material)

    def test_is_material_stays_false_on_inventory_line_even_with_material_ac(self):
        Configuration.objects.create(
            key='default_material_accounting_category', value=str(self.mat_cat.pk))
        co = self._make_co()
        li = ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='PLY', qty=Decimal('1'), price=Decimal('100.00'),
            inventory_item=self.pli.pk, accounting_category=self.mat_cat.pk,
        )
        self.assertFalse(li.is_material)

    def test_seed_new_copies_crystallization_fields(self):
        Configuration.objects.create(
            key='default_material_accounting_category', value=str(self.mat_cat.pk))
        co = self._make_co()
        ChangeOrderService.add_line_item_from_service(
            co.pk, self.service_item.pk, Decimal('4'))
        ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='Membrane', qty=Decimal('1'), price=Decimal('50.00'),
            accounting_category=self.mat_cat.pk,
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


class ReplaceInheritsTargetAcTest(ChangeOrderAcceptanceBase):
    """A REPLACE line authored without an AC inherits its target's
    (2026-08-12 — closes the gap Task 8 flagged: replace lines had no AC
    rule anywhere, so an accepted AC-less replacement became a null-AC
    agreement line and every later invoice seed demanded the fallback)."""

    def test_replace_without_ac_inherits_targets(self):
        line, _task = self._task_backed_line()
        co = self._make_co()
        li = ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=line.pk, description='Revised',
            qty=Decimal('2'), units='hour', price=Decimal('120.00'),
        )
        self.assertEqual(li.accounting_category_id, line.accounting_category_id)

    def test_replace_with_explicit_ac_is_respected(self):
        line, _task = self._task_backed_line()
        co = self._make_co()
        li = ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=line.pk, description='Revised',
            qty=Decimal('2'), units='hour', price=Decimal('120.00'),
            accounting_category=self.mat_cat.pk,
        )
        self.assertEqual(li.accounting_category_id, self.mat_cat.pk)


class SeedNewEmptyTest(ChangeOrderAcceptanceBase):
    """RM 2026-08-12: 'Start new change order' offers a choice — seed from
    the prior CO's lines, or start empty. seed_new(empty=True) is the
    empty half: same parent lineage, zero copied lines."""

    def test_seed_new_empty_copies_nothing_but_keeps_lineage(self):
        co = self._make_co()
        ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra scope', qty=Decimal('1'), price=Decimal('50.00'),
            accounting_category=self.cat.pk,
        )
        ChangeOrderService.mark_open(co.pk)
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_REJECTED)

        new_co = ChangeOrderService.seed_new(co.pk, empty=True)
        self.assertEqual(new_co.parent_id, co.pk)
        self.assertEqual(new_co.estimate_id, co.estimate_id)
        self.assertEqual(new_co.status, ChangeOrder.STATUS_DRAFT)
        self.assertEqual(
            ChangeOrderLineItem.objects.filter(change_order=new_co).count(), 0)

    def test_seed_new_endpoint_empty_body_flag(self):
        from rest_framework.test import APIClient
        from apps.core.models import User
        from tests.base import grant_atoms
        client = APIClient()
        manager = grant_atoms(
            User.objects.create_user(username='co_seed_empty', password='x'),
            'can_manage_jobs')
        client.force_authenticate(user=manager)

        co = self._make_co()
        ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra scope', qty=Decimal('1'), price=Decimal('50.00'),
            accounting_category=self.cat.pk,
        )
        ChangeOrderService.mark_open(co.pk)
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_REJECTED)

        resp = client.post(
            f'/api/change-orders/{co.pk}/seed-new/', {'empty': True}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(len(resp.data['line_items']), 0)

        resp2 = client.post(f'/api/change-orders/{co.pk}/seed-new/', {}, format='json')
        self.assertEqual(resp2.status_code, 201, resp2.data)
        self.assertEqual(len(resp2.data['line_items']), 1)


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
