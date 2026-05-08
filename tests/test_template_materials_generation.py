from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory, Configuration
from apps.contacts.models import Contact
from apps.inventory.models import (
    Material, PlanMaterial, TemplateMaterial, PriceListItem,
)
from apps.estimates.models import EstWorksheet, WorkTemplate
from apps.jobs.models import Job


class TemplateMaterialGenerationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","sheets","ea"]')
        cls.cat = AccountingCategory.objects.create(code='MAT', name='Materials')
        cls.contact = Contact.objects.create(first_name='J', last_name='D', email='j@d.com')
        cls.pli = PriceListItem.objects.create(
            code='PLI-1', units='sheets', description='Steel Sheet',
            purchase_price=Decimal('40.00'), selling_price=Decimal('60.00'),
            accounting_category=cls.cat,
        )
        cls.job = Job.objects.create(
            name='J', job_number='J-1', status=Job.STATUS_DRAFT, contact=cls.contact,
        )

    def test_pli_linked_template_material_pulls_current_pli_pricing(self):
        # TemplateMaterial set up with stale prices (the model defaults to 0
        # when not provided; the new generation flow ignores them anyway for
        # PLI-linked rows).
        wt = WorkTemplate.objects.create(template_name='T')
        TemplateMaterial.objects.create(
            work_template=wt, price_list_item=self.pli, quantity=Decimal('5'),
        )
        # PLI's prices are bumped after the TemplateMaterial was created.
        self.pli.purchase_price = Decimal('52.00')
        self.pli.selling_price = Decimal('78.00')
        self.pli.save()

        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        wt.generate_materials_for_worksheet(ws, quantity=1)

        pm = PlanMaterial.objects.get(est_worksheet=ws, plan_task__isnull=True)
        self.assertEqual(pm.unit_cost, Decimal('52.00'))   # current PLI value
        self.assertEqual(pm.sell_price, Decimal('78.00'))  # current PLI value
        self.assertEqual(pm.units, 'sheets')               # from PLI
        self.assertEqual(pm.description, 'Steel Sheet')    # from PLI

    def test_pli_linked_template_material_overrides_dont_leak(self):
        # Even if a TemplateMaterial somehow has stale prices stored on it,
        # the generation must NOT carry those forward to a PLI-linked row.
        wt = WorkTemplate.objects.create(template_name='T')
        # Force stale data via .objects.update() to bypass _populate_from_pli.
        tm = TemplateMaterial.objects.create(
            work_template=wt, price_list_item=self.pli, quantity=Decimal('5'),
        )
        TemplateMaterial.objects.filter(pk=tm.pk).update(
            description='STALE', unit_cost=Decimal('1.00'), sell_price=Decimal('2.00'),
            units='ea',
        )

        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        wt.generate_materials_for_worksheet(ws, quantity=1)

        pm = PlanMaterial.objects.get(est_worksheet=ws, plan_task__isnull=True)
        self.assertEqual(pm.unit_cost, self.pli.purchase_price)
        self.assertEqual(pm.sell_price, self.pli.selling_price)
        self.assertEqual(pm.units, self.pli.units)
        self.assertEqual(pm.description, self.pli.description)

    def test_freeform_template_material_carries_explicit_values(self):
        wt = WorkTemplate.objects.create(template_name='T')
        TemplateMaterial.objects.create(
            work_template=wt, price_list_item=None,
            description='custom thing', quantity=Decimal('3'),
            units='ea', unit_cost=Decimal('1.00'), sell_price=Decimal('2.00'),
        )
        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        wt.generate_materials_for_worksheet(ws, quantity=1)

        pm = PlanMaterial.objects.get(est_worksheet=ws, plan_task__isnull=True)
        self.assertEqual(pm.units, 'ea')
        self.assertEqual(pm.unit_cost, Decimal('1.00'))
        self.assertEqual(pm.sell_price, Decimal('2.00'))
        self.assertEqual(pm.description, 'custom thing')

    def test_generate_for_job_pli_linked_pulls_current_pli_prices(self):
        wt = WorkTemplate.objects.create(template_name='T')
        TemplateMaterial.objects.create(
            work_template=wt, price_list_item=self.pli, quantity=Decimal('5'),
        )
        self.pli.purchase_price = Decimal('52.00')
        self.pli.save()
        wt.generate_materials_for_job(self.job, quantity=1)
        m = Material.objects.get(job=self.job, task__isnull=True)
        self.assertEqual(m.unit_cost, Decimal('52.00'))

    def test_generate_for_job_freeform_carries_template_values(self):
        wt = WorkTemplate.objects.create(template_name='T')
        TemplateMaterial.objects.create(
            work_template=wt, price_list_item=None,
            description='custom', quantity=Decimal('1'),
            units='ea', unit_cost=Decimal('5.00'), sell_price=Decimal('8.00'),
        )
        wt.generate_materials_for_job(self.job, quantity=1)
        m = Material.objects.get(job=self.job, task__isnull=True)
        self.assertEqual(m.units, 'ea')
        self.assertEqual(m.unit_cost, Decimal('5.00'))
        self.assertEqual(m.sell_price, Decimal('8.00'))
