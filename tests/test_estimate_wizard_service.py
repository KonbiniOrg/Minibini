from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.models import Estimate, EstWorksheet
from apps.estimates.services import EstimateWizardService, EstimateClaimConflict
from apps.jobs.models import Job


class OpenForWorksheetTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)

    def test_creates_draft_estimate_when_none_exists(self):
        est = EstimateWizardService.open_for_worksheet(self.ws)
        self.assertEqual(est.status, Estimate.STATUS_DRAFT)
        self.assertEqual(est.job, self.job)

    def test_returns_existing_draft(self):
        first = EstimateWizardService.open_for_worksheet(self.ws)
        second = EstimateWizardService.open_for_worksheet(self.ws)
        self.assertEqual(first.pk, second.pk)

    def test_adopts_jobs_existing_draft_estimate(self):
        """One tree per job: if the job already has a draft estimate (e.g.
        created directly via the Create Estimate button), generating from the
        worksheet adopts that estimate rather than minting a second one."""
        from apps.estimates.services import EstimateService
        existing = EstimateService.create_for_job(self.job.pk)
        result = EstimateWizardService.open_for_worksheet(self.ws)
        self.assertEqual(result.pk, existing.pk)
        self.assertEqual(Estimate.objects.filter(job=self.job).count(), 1)

    def test_refuses_when_estimate_sent(self):
        """The worksheet freezes once the job's estimate is sent; generating
        an estimate from it then refuses (the model is decoupled — editability
        derives from the job's live estimate)."""
        est = EstimateWizardService.open_for_worksheet(self.ws)
        # Force the estimate to a sent state, bypassing transition validation.
        Estimate.objects.filter(pk=est.pk).update(status=Estimate.STATUS_OPEN)
        with self.assertRaises(ValidationError):
            EstimateWizardService.open_for_worksheet(self.ws)


class ClaimConflictExceptionTest(TestCase):
    def test_exception_carries_atom_ids(self):
        exc = EstimateClaimConflict(atom_ids=[{'type': 'plan_task', 'id': 1}])
        self.assertEqual(exc.atom_ids, [{'type': 'plan_task', 'id': 1}])


from apps.estimates.models import EstimateLineItem, EstimateLineItemSource
from apps.inventory.models import PlanMaterial
from apps.jobs.models import PlanTask, RateScheme


class GetSourcePoolTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )

        # PlanTask atom with billing fields (no separate PlanCharge needed)
        self.pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Setup',
            rate_scheme=self.scheme, est_qty=Decimal('2'),
        )

        # PlanMaterial atom (task-less)
        self.pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='steel', quantity=Decimal('3'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )

        self.estimate = EstimateWizardService.open_for_worksheet(self.ws)

    def test_pool_has_plan_task_and_material_atoms(self):
        pool = EstimateWizardService.get_source_pool(self.ws)
        atom_ids = [(a['type'], a['id']) for a in pool['atoms']]
        self.assertIn(('plan_task', self.pt.pk), atom_ids)
        self.assertIn(('plan_material', self.pm.pk), atom_ids)

    def test_atom_amount_uses_compute_amount(self):
        pool = EstimateWizardService.get_source_pool(self.ws)
        amounts = {(a['type'], a['id']): a['amount'] for a in pool['atoms']}
        self.assertEqual(amounts[('plan_task', self.pt.pk)], Decimal('200.00'))
        self.assertEqual(amounts[('plan_material', self.pm.pk)], Decimal('15.00'))

    def test_atoms_include_qty_and_rate(self):
        pool = EstimateWizardService.get_source_pool(self.ws)
        by_id = {(a['type'], a['id']): a for a in pool['atoms']}
        pt_atom = by_id[('plan_task', self.pt.pk)]
        self.assertEqual(pt_atom['qty'], Decimal('2'))
        self.assertEqual(pt_atom['rate'], Decimal('100.00'))
        pm_atom = by_id[('plan_material', self.pm.pk)]
        self.assertEqual(pm_atom['qty'], Decimal('3'))
        self.assertEqual(pm_atom['rate'], Decimal('5.00'))

    def test_unclaimed_atom_state(self):
        pool = EstimateWizardService.get_source_pool(self.ws)
        for a in pool['atoms']:
            self.assertEqual(a['state'], 'available')

    def test_claimed_atom_state(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('200'), description='', accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_PLAN_TASK,
            source_pk=self.pt.pk,
        )
        pool = EstimateWizardService.get_source_pool(self.ws)
        states = {(a['type'], a['id']): a['state'] for a in pool['atoms']}
        self.assertEqual(states[('plan_task', self.pt.pk)], 'claimed_by_current')
        self.assertEqual(states[('plan_material', self.pm.pk)], 'available')

    def test_source_pool_includes_plan_tasks_without_explicit_charge_creation(self):
        """Bug regression: PlanTasks should appear in the source pool even when
        no separate PlanCharge POST has fired — the billing fields are on the
        PlanTask itself now."""
        scheme = RateScheme.objects.create(
            name='Hourly Test', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('50.00'), unit_label='hour',
            accounting_category=self.cat,
        )
        pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Inline Task',
            rate_scheme=scheme, est_qty=Decimal('3.0'),
        )

        pool = EstimateWizardService.get_source_pool(self.ws)

        plan_task_ids = [a['id'] for a in pool['atoms'] if a['type'] == 'plan_task']
        self.assertIn(pt.pk, plan_task_ids)
        pt_atom = next(a for a in pool['atoms'] if a['type'] == 'plan_task' and a['id'] == pt.pk)
        self.assertEqual(pt_atom['amount'], Decimal('150.00'))



class AddAtomsToNewLineItemTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', code='LAB', is_active=True)
        self.cat2 = AccountingCategory.objects.create(name='Materials', code='MAT', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Setup',
            rate_scheme=self.scheme, est_qty=Decimal('2'),
        )
        self.pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='steel', quantity=Decimal('3'),
            sell_price=Decimal('5'), accounting_category=self.cat2,
        )
        self.estimate = EstimateWizardService.open_for_worksheet(self.ws)

    def test_creates_line_item_with_summed_price(self):
        atoms = [
            {'type': 'plan_task', 'id': self.pt.pk},
            {'type': 'plan_material', 'id': self.pm.pk},
        ]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        # 200 + 15 = 215
        self.assertEqual(li.price, Decimal('215.00'))

    def test_creates_source_rows(self):
        atoms = [{'type': 'plan_task', 'id': self.pt.pk}]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.sources.count(), 1)
        self.assertEqual(li.sources.first().source_pk, self.pt.pk)

    def test_projection_snapshot_captured_for_new_line(self):
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'plan_task', 'id': self.pt.pk}])
        li.refresh_from_db()
        key = f'plan_task:{self.pt.pk}'
        self.assertIn(key, li.projection_snapshot)
        snap = li.projection_snapshot[key]
        self.assertEqual(snap['description'], 'Setup')
        self.assertEqual(snap['accounting_category'], self.cat.pk)
        self.assertIn('qty', snap)
        self.assertIn('price', snap)

    def test_send_all_atoms_captures_snapshot_per_line(self):
        from apps.estimates.models import EstimateLineItemSource
        EstimateWizardService.send_all_atoms_to_estimate(self.ws)
        src = EstimateLineItemSource.objects.get(
            source_type='plan_task', source_pk=self.pt.pk)
        li = src.estimate_line_item
        self.assertEqual(
            li.projection_snapshot[f'plan_task:{self.pt.pk}']['description'], 'Setup')

    # ── reprojection_state (Task 2) ──────────────────────────────────────
    def _project_task_line(self):
        return EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'plan_task', 'id': self.pt.pk}])

    def test_reprojection_state_in_sync_after_projection(self):
        li = self._project_task_line()
        self.assertEqual(EstimateWizardService.reprojection_state(li), 'in_sync')

    def test_reprojection_state_overridden_when_line_hand_edited(self):
        from apps.core.services import LineItemService
        li = self._project_task_line()
        li.price = Decimal('999.00')  # hand-edit price away from the atom-derived value
        LineItemService.save_line_item(li)
        self.assertEqual(EstimateWizardService.reprojection_state(li), 'overridden')

    def test_reprojection_state_in_sync_when_untouched_atom_drifts(self):
        # An untouched (never-overridden) line whose atom drifts stays in_sync —
        # it auto-updates on re-projection; no review marker.
        li = self._project_task_line()
        self.pt.name = 'Setup CHANGED'
        self.pt.save()
        self.assertEqual(EstimateWizardService.reprojection_state(li), 'in_sync')

    def test_reprojection_state_underlying_changed_when_overridden_and_atom_drifts(self):
        from apps.core.services import LineItemService
        li = self._project_task_line()
        li.description = 'My label'  # hand-edit (override)
        LineItemService.save_line_item(li)
        self.pt.name = 'Setup CHANGED'  # then the atom drifts
        self.pt.save()
        self.assertEqual(EstimateWizardService.reprojection_state(li), 'underlying_changed')

    def test_reprojection_state_underlying_removed_when_atom_deleted(self):
        li = self._project_task_line()
        self.pt.delete()
        self.assertEqual(EstimateWizardService.reprojection_state(li), 'underlying_removed')

    def test_reprojection_state_none_for_hand_added_line(self):
        from apps.estimates.models import EstimateLineItem
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, description='manual', qty=Decimal('1'),
            units='none', price=Decimal('10.00'))
        self.assertIsNone(EstimateWizardService.reprojection_state(li))

    # ── re-projection updates in_sync lines, leaves overridden (Task 3) ──
    def test_reprojection_updates_in_sync_line_after_atom_change(self):
        li = self._project_task_line()
        self.pt.name = 'Setup CHANGED'
        self.pt.est_qty = Decimal('5')
        self.pt.save()
        EstimateWizardService.send_all_atoms_to_estimate(self.ws)
        li.refresh_from_db()
        self.assertEqual(li.description, 'Setup CHANGED')
        self.assertEqual(li.qty, Decimal('5'))

    def test_reprojection_leaves_overridden_line_untouched(self):
        from apps.core.services import LineItemService
        li = self._project_task_line()
        li.description = 'custom'
        LineItemService.save_line_item(li)
        self.pt.name = 'Setup CHANGED'
        self.pt.save()
        EstimateWizardService.send_all_atoms_to_estimate(self.ws)
        li.refresh_from_db()
        self.assertEqual(li.description, 'custom')

    # ── editing a line re-baselines its snapshot (Task 3, user rule) ─────
    def test_edit_rebaselines_snapshot_clearing_underlying_changed(self):
        from apps.core.services import LineItemService
        from apps.estimates.services import EstimateService
        li = self._project_task_line()
        li.description = 'custom'  # override
        LineItemService.save_line_item(li)
        self.pt.name = 'Setup CHANGED'  # atom drift -> underlying_changed
        self.pt.save()
        self.assertEqual(EstimateWizardService.reprojection_state(li), 'underlying_changed')
        # Editing the line again re-baselines the snapshot -> drops to 'overridden'.
        EstimateService.update_line_item(li.line_item_id, description='custom2')
        li.refresh_from_db()
        self.assertEqual(EstimateWizardService.reprojection_state(li), 'overridden')

    # ── reconcile: re-pull / keep-mine (Task 4) ──────────────────────────
    def _overridden_then_drifted(self):
        from apps.core.services import LineItemService
        li = self._project_task_line()
        li.description = 'custom'
        LineItemService.save_line_item(li)
        self.pt.name = 'Setup CHANGED'
        self.pt.save()
        return li

    def test_repull_takes_atom_values_and_clears_flag(self):
        li = self._overridden_then_drifted()
        EstimateWizardService.repull_line_item(li.line_item_id)
        li.refresh_from_db()
        self.assertEqual(li.description, 'Setup CHANGED')  # fresh projection from the atom
        self.assertEqual(EstimateWizardService.reprojection_state(li), 'in_sync')

    def test_keep_mine_keeps_values_and_clears_flag(self):
        li = self._overridden_then_drifted()
        EstimateWizardService.keep_mine_line_item(li.line_item_id)
        li.refresh_from_db()
        self.assertEqual(li.description, 'custom')  # my value kept
        self.assertEqual(EstimateWizardService.reprojection_state(li), 'overridden')

    def test_repull_on_removed_atom_drops_dangling_source(self):
        li = self._project_task_line()
        self.pt.delete()  # -> underlying_removed
        EstimateWizardService.repull_line_item(li.line_item_id)
        li.refresh_from_db()
        self.assertEqual(li.sources.count(), 0)
        self.assertIsNone(EstimateWizardService.reprojection_state(li))

    def test_reconcile_blocked_on_non_draft_estimate(self):
        from django.core.exceptions import ValidationError as DjangoValidationError
        from apps.estimates.models import Estimate
        li = self._project_task_line()
        Estimate.objects.filter(pk=self.estimate.pk).update(status=Estimate.STATUS_OPEN)
        with self.assertRaises(DjangoValidationError):
            EstimateWizardService.keep_mine_line_item(li.line_item_id)

    def test_uniform_category_kept(self):
        # Both atoms in same category
        pm_same_cat = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='m', quantity=Decimal('1'),
            sell_price=Decimal('1'), accounting_category=self.cat,
        )
        atoms = [
            {'type': 'plan_task', 'id': self.pt.pk},
            {'type': 'plan_material', 'id': pm_same_cat.pk},
        ]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.accounting_category, self.cat)

    def test_mixed_category_left_null(self):
        atoms = [
            {'type': 'plan_task', 'id': self.pt.pk},
            {'type': 'plan_material', 'id': self.pm.pk},
        ]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertIsNone(li.accounting_category)

    def test_double_claim_raises(self):
        atoms = [{'type': 'plan_task', 'id': self.pt.pk}]
        EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        with self.assertRaises(EstimateClaimConflict):
            EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)

    def test_single_plan_task_atom_copy_over(self):
        # pt has est_qty=2, scheme rate=100, no modifiers -> qty=2, price=100, units=hour
        atoms = [{'type': 'plan_task', 'id': self.pt.pk}]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.qty, Decimal('2'))
        self.assertEqual(li.price, Decimal('100'))
        self.assertEqual(li.units, 'hour')

    def test_single_plan_material_atom_copy_over(self):
        # pm has quantity=3, sell_price=5, no inventory_item -> qty=3, price=5, units='none'
        atoms = [{'type': 'plan_material', 'id': self.pm.pk}]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.qty, Decimal('3'))
        self.assertEqual(li.price, Decimal('5'))
        self.assertEqual(li.units, 'none')

    def test_multi_atom_line_qty_1_units_none(self):
        atoms = [
            {'type': 'plan_task', 'id': self.pt.pk},
            {'type': 'plan_material', 'id': self.pm.pk},
        ]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.qty, Decimal('1'))
        self.assertEqual(li.units, 'none')

    def test_refuses_non_draft_estimate(self):
        # Use update() to bypass model-level transition validation
        Estimate.objects.filter(pk=self.estimate.pk).update(status=Estimate.STATUS_OPEN)
        self.estimate.refresh_from_db()
        atoms = [{'type': 'plan_task', 'id': self.pt.pk}]
        with self.assertRaises(ValidationError):
            EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)


class AddAtomsToExistingLineItemTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt1 = PlanTask.objects.create(
            est_worksheet=self.ws, name='A',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        self.pt2 = PlanTask.objects.create(
            est_worksheet=self.ws, name='B',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        self.estimate = EstimateWizardService.open_for_worksheet(self.ws)
        self.li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'plan_task', 'id': self.pt1.pk}],
        )

    def test_appends_source(self):
        EstimateWizardService.add_atoms_to_line_item(
            self.li, [{'type': 'plan_task', 'id': self.pt2.pk}],
        )
        self.assertEqual(self.li.sources.count(), 2)

    def test_add_makes_uniform_bundle_resummarized(self):
        # li starts as a single-atom copy-over (qty=1, price=$100). Adding
        # pt2 makes {pt1, pt2} a uniform same-scheme bundle, re-summarized:
        # qty = summed est_qty = 2, price = scheme rate $100.
        EstimateWizardService.add_atoms_to_line_item(
            self.li, [{'type': 'plan_task', 'id': self.pt2.pk}],
        )
        self.li.refresh_from_db()
        self.assertEqual(self.li.qty, Decimal('2'))
        self.assertEqual(self.li.price, Decimal('100.00'))

    def test_preserves_overridden_price(self):
        # Override the price away from in-sync value
        self.li.price = Decimal('500.00')
        self.li.save()
        EstimateWizardService.add_atoms_to_line_item(
            self.li, [{'type': 'plan_task', 'id': self.pt2.pk}],
        )
        self.li.refresh_from_db()
        self.assertEqual(self.li.price, Decimal('500.00'))

    def test_double_claim_raises(self):
        with self.assertRaises(EstimateClaimConflict):
            EstimateWizardService.add_atoms_to_line_item(
                self.li, [{'type': 'plan_task', 'id': self.pt1.pk}],
            )


class RemoveAtomsFromLineItemTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt1 = PlanTask.objects.create(
            est_worksheet=self.ws, name='A',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        self.pt2 = PlanTask.objects.create(
            est_worksheet=self.ws, name='B',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        self.estimate = EstimateWizardService.open_for_worksheet(self.ws)
        self.li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate,
            [
                {'type': 'plan_task', 'id': self.pt1.pk},
                {'type': 'plan_task', 'id': self.pt2.pk},
            ],
        )

    def test_removes_subset(self):
        src_to_remove = self.li.sources.filter(source_pk=self.pt1.pk).first()
        result = EstimateWizardService.remove_atoms_from_line_item(
            self.li, [src_to_remove.source_id],
        )
        self.assertFalse(result['line_item_deleted'])
        self.assertEqual(self.li.sources.count(), 1)

    def test_recomputes_price_when_in_sync(self):
        # initial $200 / 1 qty. Remove pt1 -> remaining sum = $100, expected price = $100.
        src_to_remove = self.li.sources.filter(source_pk=self.pt1.pk).first()
        EstimateWizardService.remove_atoms_from_line_item(
            self.li, [src_to_remove.source_id],
        )
        self.li.refresh_from_db()
        self.assertEqual(self.li.price, Decimal('100.00'))

    def test_preserves_overridden_price(self):
        self.li.price = Decimal('999.00')
        self.li.save()
        src_to_remove = self.li.sources.filter(source_pk=self.pt1.pk).first()
        EstimateWizardService.remove_atoms_from_line_item(
            self.li, [src_to_remove.source_id],
        )
        self.li.refresh_from_db()
        self.assertEqual(self.li.price, Decimal('999.00'))

    def test_deletes_line_item_when_all_sources_removed(self):
        all_ids = list(self.li.sources.values_list('source_id', flat=True))
        result = EstimateWizardService.remove_atoms_from_line_item(self.li, all_ids)
        self.assertTrue(result['line_item_deleted'])
        from apps.estimates.models import EstimateLineItem
        self.assertFalse(EstimateLineItem.objects.filter(pk=self.li.pk).exists())

    def test_deletes_line_item_even_if_overridden(self):
        """Removing all sources deletes the line item regardless of price override."""
        self.li.price = Decimal('999.00')
        self.li.save()
        all_ids = list(self.li.sources.values_list('source_id', flat=True))
        result = EstimateWizardService.remove_atoms_from_line_item(self.li, all_ids)
        self.assertTrue(result['line_item_deleted'])
        from apps.estimates.models import EstimateLineItem
        self.assertFalse(EstimateLineItem.objects.filter(pk=self.li.pk).exists())

    def test_refuses_mutation_on_non_draft_estimate(self):
        """Wizard refuses remove operation on non-draft estimates."""
        # Bypass model transition validation (same pattern used elsewhere in this file)
        Estimate.objects.filter(pk=self.estimate.pk).update(status=Estimate.STATUS_OPEN)
        self.estimate.refresh_from_db()
        self.li.estimate = self.estimate  # refresh the cached estimate on the line item
        src_to_remove = self.li.sources.first()
        with self.assertRaises(ValidationError):
            EstimateWizardService.remove_atoms_from_line_item(
                self.li, [src_to_remove.source_id],
            )

    def test_remove_from_in_sync_uniform_bundle_resummarizes(self):
        # Manual qty/price on an in-sync line item is replaced by
        # re-summarization when removal leaves a uniform same-scheme bundle.
        self.li.qty = Decimal('2')
        self.li.price = Decimal('100.00')
        self.li.save()
        src_to_remove = self.li.sources.filter(source_pk=self.pt1.pk).first()
        EstimateWizardService.remove_atoms_from_line_item(
            self.li, [src_to_remove.source_id],
        )
        self.li.refresh_from_db()
        self.assertEqual(self.li.qty, Decimal('1'))
        self.assertEqual(self.li.price, Decimal('100.00'))

    def test_renumbers_siblings_when_auto_delete_fires(self):
        """When all atoms are removed and the line item auto-deletes, the
        remaining siblings must be renumbered to close the gap."""
        # self.li is line 1 (from setUp). Add two more line items so we have 1, 2, 3.
        pt3 = PlanTask.objects.create(
            est_worksheet=self.ws, name='C',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        pt4 = PlanTask.objects.create(
            est_worksheet=self.ws, name='D',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        li2 = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'plan_task', 'id': pt3.pk}],
        )
        li3 = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'plan_task', 'id': pt4.pk}],
        )
        self.assertEqual(self.li.line_number, 1)
        self.assertEqual(li2.line_number, 2)
        self.assertEqual(li3.line_number, 3)

        # Remove all atoms from line 1 → auto-delete fires
        all_ids = list(self.li.sources.values_list('source_id', flat=True))
        result = EstimateWizardService.remove_atoms_from_line_item(self.li, all_ids)
        self.assertTrue(result['line_item_deleted'])

        li2.refresh_from_db()
        li3.refresh_from_db()
        self.assertEqual(li2.line_number, 1)
        self.assertEqual(li3.line_number, 2)


class SendAllAtomsTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='A',
            rate_scheme=self.scheme, est_qty=Decimal('2'),
        )
        self.pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='steel', quantity=Decimal('3'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )

    def test_creates_one_line_item_per_unclaimed_atom(self):
        result = EstimateWizardService.send_all_atoms_to_estimate(self.ws)
        self.assertEqual(result['created_count'], 2)
        from apps.estimates.models import EstimateLineItem
        line_items = EstimateLineItem.objects.filter(estimate=result['estimate'])
        self.assertEqual(line_items.count(), 2)

    def test_each_line_item_has_one_source(self):
        result = EstimateWizardService.send_all_atoms_to_estimate(self.ws)
        from apps.estimates.models import EstimateLineItem
        for li in EstimateLineItem.objects.filter(estimate=result['estimate']):
            self.assertEqual(li.sources.count(), 1)

    def test_skips_already_claimed_atoms(self):
        # Pre-claim the PlanTask via an existing line item
        estimate = EstimateWizardService.open_for_worksheet(self.ws)
        EstimateWizardService.add_atoms_to_new_line_item(
            estimate, [{'type': 'plan_task', 'id': self.pt.pk}],
        )
        result = EstimateWizardService.send_all_atoms_to_estimate(self.ws)
        # Only the PlanMaterial gets a new line item
        self.assertEqual(result['created_count'], 1)

    def test_amount_matches_compute_amount(self):
        result = EstimateWizardService.send_all_atoms_to_estimate(self.ws)
        from apps.estimates.models import EstimateLineItem
        # qty * price totals must equal each atom's compute_amount.
        # PlanTask: est_qty=2, rate=$100 → qty=2, price=100, total=$200.
        # PlanMaterial: quantity=3, sell_price=$5 → qty=3, price=5, total=$15.
        totals = sorted(
            li.qty * li.price
            for li in EstimateLineItem.objects.filter(estimate=result['estimate'])
        )
        self.assertEqual(totals, [Decimal('15.00'), Decimal('200.00')])

    def test_send_all_recomputes_existing_adjustment(self):
        """A percentage adjustment added before send-all is recomputed against
        the base lines send-all creates (the bulk path recomputes once at end)."""
        from apps.estimates.services import EstimateService
        estimate = EstimateWizardService.open_for_worksheet(self.ws)
        rush = RateScheme.objects.create(
            name='Rush', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='none', accounting_category=self.cat,
        )
        adj = EstimateService.add_adjustment_line(
            estimate, adjustment_service_id=rush.pk, target_category_ids=[],
        )
        self.assertEqual(adj.price, Decimal('0.00'))  # no base lines yet
        EstimateWizardService.send_all_atoms_to_estimate(self.ws)
        adj.refresh_from_db()
        # base = $200 (task) + $15 (material) = $215; 10% = $21.50
        self.assertEqual(adj.price, Decimal('21.50'))

    def test_qty_and_price_split_per_atom(self):
        """Per-unit qty/price must reflect the source atom, not collapse to 1×total."""
        result = EstimateWizardService.send_all_atoms_to_estimate(self.ws)
        from apps.estimates.models import EstimateLineItem
        rows = sorted(
            EstimateLineItem.objects.filter(estimate=result['estimate'])
            .values_list('qty', 'price'),
            key=lambda t: t[0],
        )
        self.assertEqual(rows, [
            (Decimal('2.00'), Decimal('100.00')),  # PlanTask
            (Decimal('3.00'), Decimal('5.00')),    # PlanMaterial
        ])

    def test_returns_estimate(self):
        result = EstimateWizardService.send_all_atoms_to_estimate(self.ws)
        self.assertEqual(result['estimate'].job, self.job)
        self.assertEqual(result['estimate'].status, Estimate.STATUS_DRAFT)

    def test_worker_time_task_with_modifier_does_not_raise(self):
        """A worker-entered-time task whose rate+modifier yields >2 decimals
        (99.99 × 1.05 = 104.9895) must carry to an EstimateLineItem without
        tripping the price DecimalField's 2-place validation."""
        scheme = RateScheme.objects.create(
            name='Worker Time', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('99.99'), unit_label='hour',
            modifiers=[{'key': 'rush', 'label': 'Rush', 'percent': 5}],
            accounting_category=self.cat,
        )
        pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Rushed work',
            rate_scheme=scheme, est_qty=Decimal('2'),
            active_modifiers=['rush'],
        )
        result = EstimateWizardService.send_all_atoms_to_estimate(self.ws)
        from apps.estimates.models import EstimateLineItem
        li = EstimateLineItem.objects.get(
            estimate=result['estimate'], description='Rushed work')
        self.assertEqual(li.price, Decimal('104.99'))


class AddAtomsToNewLineItemDescriptionTest(TestCase):
    """Description is pre-filled from the source atom when exactly one atom is added."""

    def setUp(self):
        super().setUp()
        from apps.contacts.models import Contact
        from apps.jobs.models import Job, PlanTask, RateScheme
        from apps.inventory.models import PlanMaterial
        from apps.estimates.models import EstWorksheet
        from apps.core.models import AccountingCategory, Configuration

        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')

        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f-d@l.test',
            mobile_number='555-1',
        )
        self.job = Job.objects.create(job_number='J-desc', contact=contact)
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.cat = AccountingCategory.objects.create(code='D', name='D')
        self.scheme = RateScheme.objects.create(
            name='Hourly-d', algorithm='flat_fee', rate=Decimal('10'),
            unit_label='ea', accounting_category=self.cat,
        )
        self.pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Cut sign blank',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        self.pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='3/4" plywood',
            quantity=Decimal('2'), unit_cost=Decimal('5'),
            sell_price=Decimal('10'), accounting_category=self.cat,
        )
        self.estimate = EstimateWizardService.open_for_worksheet(self.ws)

    def test_single_plan_task_atom_seeds_description_from_name(self):
        from apps.estimates.services import EstimateWizardService
        atoms = [{'type': 'plan_task', 'id': self.pt.pk}]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.description, 'Cut sign blank')

    def test_single_plan_material_atom_seeds_description(self):
        from apps.estimates.services import EstimateWizardService
        atoms = [{'type': 'plan_material', 'id': self.pm.pk}]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.description, '3/4" plywood')

    def test_multiple_atoms_leaves_description_blank(self):
        from apps.estimates.services import EstimateWizardService
        atoms = [
            {'type': 'plan_task', 'id': self.pt.pk},
            {'type': 'plan_material', 'id': self.pm.pk},
        ]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.description, '')

    def test_claiming_line_number_exposed_for_current_estimate_claim(self):
        """Source pool atoms claimed by the current estimate's line items
        should expose claiming_line_number (not just claiming_line_item_id)
        so the frontend can show the user-facing line number."""
        from apps.estimates.services import EstimateWizardService
        # self.pt is a PlanTask on self.ws; claim it on a new line item.
        atoms = [{'type': 'plan_task', 'id': self.pt.pk}]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        pool = EstimateWizardService.get_source_pool(self.ws)
        claimed = next(a for a in pool['atoms'] if a['id'] == self.pt.pk)
        self.assertEqual(claimed['state'], 'claimed_by_current')
        self.assertEqual(claimed['claiming_line_number'], li.line_number)
        # Existing claiming_line_item_id stays for any callers that use it.
        self.assertEqual(claimed['claiming_line_item_id'], li.pk)
