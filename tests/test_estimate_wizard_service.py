from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateWizardService, EstimateClaimConflict
from apps.jobs.models import Job


class ClaimConflictExceptionTest(TestCase):
    def test_exception_carries_atom_ids(self):
        exc = EstimateClaimConflict(atom_ids=[{'type': 'task', 'id': 1}])
        self.assertEqual(exc.atom_ids, [{'type': 'task', 'id': 1}])


from apps.estimates.models import EstimateLineItem, EstimateLineItemSource
from apps.inventory.models import Material
from apps.jobs.models import Task, RateScheme


class GetSourcePoolTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )

        # Task atom with billing fields (no separate PlanCharge needed)
        self.pt = Task.objects.create(
            job=self.job, name='Setup',
            rate_scheme=self.scheme, est_qty=Decimal('2'),
        )

        # Material atom (task-less)
        self.pm = Material.objects.create(
            job=self.job, description='steel', quantity=Decimal('3'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )

        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number=self.job.job_number, version=1,
            status=Estimate.STATUS_DRAFT,
        )

    def test_pool_has_task_and_material_atoms(self):
        pool = EstimateWizardService.get_source_pool(self.estimate)
        atom_ids = [(a['type'], a['id']) for a in pool['atoms']]
        self.assertIn(('task', self.pt.pk), atom_ids)
        self.assertIn(('material', self.pm.pk), atom_ids)

    def test_atom_amount_uses_compute_amount(self):
        pool = EstimateWizardService.get_source_pool(self.estimate)
        amounts = {(a['type'], a['id']): a['amount'] for a in pool['atoms']}
        self.assertEqual(amounts[('task', self.pt.pk)], Decimal('200.00'))
        self.assertEqual(amounts[('material', self.pm.pk)], Decimal('15.00'))

    def test_atoms_include_qty_and_rate(self):
        pool = EstimateWizardService.get_source_pool(self.estimate)
        by_id = {(a['type'], a['id']): a for a in pool['atoms']}
        pt_atom = by_id[('task', self.pt.pk)]
        self.assertEqual(pt_atom['qty'], Decimal('2'))
        self.assertEqual(pt_atom['rate'], Decimal('100.00'))
        pm_atom = by_id[('material', self.pm.pk)]
        self.assertEqual(pm_atom['qty'], Decimal('3'))
        self.assertEqual(pm_atom['rate'], Decimal('5.00'))

    def test_unclaimed_atom_state(self):
        pool = EstimateWizardService.get_source_pool(self.estimate)
        for a in pool['atoms']:
            self.assertEqual(a['state'], 'available')

    def test_claimed_atom_state(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('200'), description='', accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.pt.pk,
        )
        pool = EstimateWizardService.get_source_pool(self.estimate)
        states = {(a['type'], a['id']): a['state'] for a in pool['atoms']}
        self.assertEqual(states[('task', self.pt.pk)], 'claimed_by_current')
        self.assertEqual(states[('material', self.pm.pk)], 'available')

    def test_source_pool_includes_tasks_without_explicit_charge_creation(self):
        """Bug regression: Tasks should appear in the source pool even when
        no separate PlanCharge POST has fired — the billing fields are on the
        Task itself now."""
        scheme = RateScheme.objects.create(
            name='Hourly Test', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('50.00'), unit_label='hour',
            accounting_category=self.cat,
        )
        pt = Task.objects.create(
            job=self.job, name='Inline Task',
            rate_scheme=scheme, est_qty=Decimal('3.0'),
        )

        pool = EstimateWizardService.get_source_pool(self.estimate)

        task_ids = [a['id'] for a in pool['atoms'] if a['type'] == 'task']
        self.assertIn(pt.pk, task_ids)
        pt_atom = next(a for a in pool['atoms'] if a['type'] == 'task' and a['id'] == pt.pk)
        self.assertEqual(pt_atom['amount'], Decimal('150.00'))



class AddAtomsToNewLineItemTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='Labor', code='LAB', is_active=True)
        self.cat2 = AccountingCategory.objects.create(name='Materials', code='MAT', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt = Task.objects.create(
            job=self.job, name='Setup',
            rate_scheme=self.scheme, est_qty=Decimal('2'),
        )
        self.pm = Material.objects.create(
            job=self.job, description='steel', quantity=Decimal('3'),
            sell_price=Decimal('5'), accounting_category=self.cat2,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number=self.job.job_number, version=1,
            status=Estimate.STATUS_DRAFT,
        )

    def test_creates_line_item_with_summed_price(self):
        atoms = [
            {'type': 'task', 'id': self.pt.pk},
            {'type': 'material', 'id': self.pm.pk},
        ]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        # 200 + 15 = 215
        self.assertEqual(li.price, Decimal('215.00'))

    def test_creates_source_rows(self):
        atoms = [{'type': 'task', 'id': self.pt.pk}]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.sources.count(), 1)
        self.assertEqual(li.sources.first().source_pk, self.pt.pk)

    def test_uniform_category_kept(self):
        # Both atoms in same category
        pm_same_cat = Material.objects.create(
            job=self.job, description='m', quantity=Decimal('1'),
            sell_price=Decimal('1'), accounting_category=self.cat,
        )
        atoms = [
            {'type': 'task', 'id': self.pt.pk},
            {'type': 'material', 'id': pm_same_cat.pk},
        ]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.accounting_category, self.cat)

    def test_mixed_category_left_null(self):
        atoms = [
            {'type': 'task', 'id': self.pt.pk},
            {'type': 'material', 'id': self.pm.pk},
        ]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertIsNone(li.accounting_category)

    def test_double_claim_raises(self):
        atoms = [{'type': 'task', 'id': self.pt.pk}]
        EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        with self.assertRaises(EstimateClaimConflict):
            EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)

    def test_single_task_atom_copy_over(self):
        # pt has est_qty=2, scheme rate=100, no modifiers -> qty=2, price=100, units=hour
        atoms = [{'type': 'task', 'id': self.pt.pk}]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.qty, Decimal('2'))
        self.assertEqual(li.price, Decimal('100'))
        self.assertEqual(li.units, 'hour')

    def test_single_material_atom_copy_over(self):
        # pm has quantity=3, sell_price=5, no inventory_item -> qty=3, price=5, units='none'
        atoms = [{'type': 'material', 'id': self.pm.pk}]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.qty, Decimal('3'))
        self.assertEqual(li.price, Decimal('5'))
        self.assertEqual(li.units, 'none')

    def test_multi_atom_line_qty_1_units_none(self):
        atoms = [
            {'type': 'task', 'id': self.pt.pk},
            {'type': 'material', 'id': self.pm.pk},
        ]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.qty, Decimal('1'))
        self.assertEqual(li.units, 'none')

    def test_refuses_non_draft_estimate(self):
        # Use update() to bypass model-level transition validation
        Estimate.objects.filter(pk=self.estimate.pk).update(status=Estimate.STATUS_OPEN)
        self.estimate.refresh_from_db()
        atoms = [{'type': 'task', 'id': self.pt.pk}]
        with self.assertRaises(ValidationError):
            EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)


class AddAtomsToExistingLineItemTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt1 = Task.objects.create(
            job=self.job, name='A',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        self.pt2 = Task.objects.create(
            job=self.job, name='B',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number=self.job.job_number, version=1,
            status=Estimate.STATUS_DRAFT,
        )
        self.li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'task', 'id': self.pt1.pk}],
        )

    def test_appends_source(self):
        EstimateWizardService.add_atoms_to_line_item(
            self.li, [{'type': 'task', 'id': self.pt2.pk}],
        )
        self.assertEqual(self.li.sources.count(), 2)

    def test_add_makes_uniform_bundle_resummarized(self):
        # li starts as a single-atom copy-over (qty=1, price=$100). Adding
        # pt2 makes {pt1, pt2} a uniform same-scheme bundle, re-summarized:
        # qty = summed est_qty = 2, price = scheme rate $100.
        EstimateWizardService.add_atoms_to_line_item(
            self.li, [{'type': 'task', 'id': self.pt2.pk}],
        )
        self.li.refresh_from_db()
        self.assertEqual(self.li.qty, Decimal('2'))
        self.assertEqual(self.li.price, Decimal('100.00'))

    def test_preserves_overridden_price(self):
        # Override the price away from in-sync value
        self.li.price = Decimal('500.00')
        self.li.save()
        EstimateWizardService.add_atoms_to_line_item(
            self.li, [{'type': 'task', 'id': self.pt2.pk}],
        )
        self.li.refresh_from_db()
        self.assertEqual(self.li.price, Decimal('500.00'))

    def test_double_claim_raises(self):
        with self.assertRaises(EstimateClaimConflict):
            EstimateWizardService.add_atoms_to_line_item(
                self.li, [{'type': 'task', 'id': self.pt1.pk}],
            )


class RemoveAtomsFromLineItemTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt1 = Task.objects.create(
            job=self.job, name='A',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        self.pt2 = Task.objects.create(
            job=self.job, name='B',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number=self.job.job_number, version=1,
            status=Estimate.STATUS_DRAFT,
        )
        self.li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate,
            [
                {'type': 'task', 'id': self.pt1.pk},
                {'type': 'task', 'id': self.pt2.pk},
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
        pt3 = Task.objects.create(
            job=self.job, name='C',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        pt4 = Task.objects.create(
            job=self.job, name='D',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        li2 = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'task', 'id': pt3.pk}],
        )
        li3 = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'task', 'id': pt4.pk}],
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


class AddAtomsToNewLineItemDescriptionTest(TestCase):
    """Description is pre-filled from the source atom when exactly one atom is added."""

    def setUp(self):
        super().setUp()
        from apps.contacts.models import Contact
        from apps.jobs.models import Job, Task, RateScheme
        from apps.inventory.models import Material
        from apps.estimates.models import Estimate
        from apps.core.models import AccountingCategory, Configuration

        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})

        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f-d@l.test',
            mobile_number='555-1',
        )
        self.job = Job.objects.create(job_number='J-desc', contact=contact)
        self.cat = AccountingCategory.objects.create(code='D', name='D')
        self.scheme = RateScheme.objects.create(
            name='Hourly-d', algorithm='entered_qty', rate=Decimal('10'),
            unit_label='ea', accounting_category=self.cat,
        )
        self.pt = Task.objects.create(
            job=self.job, name='Cut sign blank',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        self.pm = Material.objects.create(
            job=self.job, description='3/4" plywood',
            quantity=Decimal('2'), unit_cost=Decimal('5'),
            sell_price=Decimal('10'), accounting_category=self.cat,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number=self.job.job_number, version=1,
            status=Estimate.STATUS_DRAFT,
        )

    def test_single_task_atom_seeds_description_from_name(self):
        from apps.estimates.services import EstimateWizardService
        atoms = [{'type': 'task', 'id': self.pt.pk}]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.description, 'Cut sign blank')

    def test_single_material_atom_seeds_description(self):
        from apps.estimates.services import EstimateWizardService
        atoms = [{'type': 'material', 'id': self.pm.pk}]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.description, '3/4" plywood')

    def test_multiple_atoms_leaves_description_blank(self):
        from apps.estimates.services import EstimateWizardService
        atoms = [
            {'type': 'task', 'id': self.pt.pk},
            {'type': 'material', 'id': self.pm.pk},
        ]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.description, '')

    def test_claiming_line_number_exposed_for_current_estimate_claim(self):
        """Source pool atoms claimed by the current estimate's line items
        should expose claiming_line_number (not just claiming_line_item_id)
        so the frontend can show the user-facing line number."""
        from apps.estimates.services import EstimateWizardService
        # self.pt is a Task on self.job; claim it on a new line item.
        atoms = [{'type': 'task', 'id': self.pt.pk}]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        pool = EstimateWizardService.get_source_pool(self.estimate)
        claimed = next(a for a in pool['atoms'] if a['id'] == self.pt.pk)
        self.assertEqual(claimed['state'], 'claimed_by_current')
        self.assertEqual(claimed['claiming_line_number'], li.line_number)
        # Existing claiming_line_item_id stays for any callers that use it.
        self.assertEqual(claimed['claiming_line_item_id'], li.pk)
