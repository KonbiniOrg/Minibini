from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.estimates.models import Estimate, EstWorksheet
from apps.estimates.services import EstimateWizardService, EstimateClaimConflict
from apps.jobs.models import Job


class OpenForWorksheetTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)

    def test_creates_draft_estimate_when_none_exists(self):
        est = EstimateWizardService.open_for_worksheet(self.ws)
        self.assertEqual(est.status, Estimate.STATUS_DRAFT)
        self.assertEqual(est.job, self.job)
        self.ws.refresh_from_db()
        self.assertEqual(self.ws.estimate, est)

    def test_returns_existing_draft(self):
        first = EstimateWizardService.open_for_worksheet(self.ws)
        second = EstimateWizardService.open_for_worksheet(self.ws)
        self.assertEqual(first.pk, second.pk)

    def test_refuses_finalized_worksheet(self):
        self.ws.status = EstWorksheet.STATUS_FINAL
        self.ws.save()
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
        Configuration.objects.create(key='job_counter', value='0')
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
        Configuration.objects.create(key='job_counter', value='0')
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
        Configuration.objects.create(key='job_counter', value='0')
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

    def test_recomputes_price_when_in_sync(self):
        # Initial price = $100 (1 atom). After adding 2nd atom, expect $200 (2 × $100 / 1 qty).
        EstimateWizardService.add_atoms_to_line_item(
            self.li, [{'type': 'plan_task', 'id': self.pt2.pk}],
        )
        self.li.refresh_from_db()
        self.assertEqual(self.li.price, Decimal('200.00'))

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
        Configuration.objects.create(key='job_counter', value='0')
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

    def test_recomputes_per_unit_when_in_sync_with_qty_gt_1(self):
        """Recompute uses per-unit math: new_price = sum / qty."""
        # Set qty to 2 and in-sync price to sum/qty = 200/2 = 100
        self.li.qty = Decimal('2')
        self.li.price = Decimal('100.00')
        self.li.save()
        src_to_remove = self.li.sources.filter(source_pk=self.pt1.pk).first()
        EstimateWizardService.remove_atoms_from_line_item(
            self.li, [src_to_remove.source_id],
        )
        self.li.refresh_from_db()
        # After removal: remaining sum = $100, qty=2, expected = 50.00
        self.assertEqual(self.li.price, Decimal('50.00'))


class SendAllAtomsTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
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
        prices = sorted(
            EstimateLineItem.objects.filter(estimate=result['estimate']).values_list('price', flat=True)
        )
        # PlanTask: 2 × $100 = $200; PlanMaterial: 3 × $5 = $15
        self.assertEqual(prices, [Decimal('15.00'), Decimal('200.00')])

    def test_returns_estimate(self):
        result = EstimateWizardService.send_all_atoms_to_estimate(self.ws)
        self.assertEqual(result['estimate'].job, self.job)
        self.assertEqual(result['estimate'].status, Estimate.STATUS_DRAFT)


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
        Configuration.objects.create(key='job_counter', value='0')

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
