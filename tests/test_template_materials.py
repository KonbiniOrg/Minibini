from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.jobs.models import Job
from apps.estimates.models import WorkTemplate, EstWorksheet
from apps.inventory.models import TemplateMaterial, PlanMaterial, Earmark, PriceListItem


class TemplateMaterialTest(TestCase):
    def test_create_template_material(self):
        wt = WorkTemplate.objects.create(
            template_name='widget', base_price=Decimal('0.00'), is_active=True,
        )
        tm = TemplateMaterial.objects.create(
            work_template=wt, description='screws', quantity=Decimal('10.00'),
        )
        self.assertEqual(list(wt.materials.all()), [tm])
        self.assertEqual(tm.sort_order, 0)

    def test_template_material_all_material_fields_optional(self):
        wt = WorkTemplate.objects.create(
            template_name='blank', base_price=Decimal('0.00'), is_active=True,
        )
        tm = TemplateMaterial.objects.create(work_template=wt)
        self.assertEqual(tm.quantity, Decimal('0.00'))


class GenerateMaterialsForWorksheetTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test', last_name='User')

    def test_generates_taskless_plan_materials(self):
        wt = WorkTemplate.objects.create(
            template_name='t', base_price=Decimal('0'), is_active=True,
        )
        TemplateMaterial.objects.create(
            work_template=wt, description='screws', quantity=Decimal('10'),
        )
        TemplateMaterial.objects.create(
            work_template=wt, description='nails', quantity=Decimal('5'),
        )
        job = Job.objects.create(job_number='JOB-GM-1', contact=self.contact)
        ws = EstWorksheet.objects.create(job=job)
        wt.generate_materials_for_worksheet(ws, quantity=1)
        pms = list(PlanMaterial.objects.filter(est_worksheet=ws, plan_task__isnull=True))
        self.assertEqual(len(pms), 2)
        self.assertEqual({p.description for p in pms}, {'screws', 'nails'})

    def test_quantity_multiplies_generation(self):
        wt = WorkTemplate.objects.create(
            template_name='t2', base_price=Decimal('0'), is_active=True,
        )
        TemplateMaterial.objects.create(
            work_template=wt, description='screws', quantity=Decimal('10'),
        )
        job = Job.objects.create(job_number='JOB-GM-2', contact=self.contact)
        ws = EstWorksheet.objects.create(job=job)
        wt.generate_materials_for_worksheet(ws, quantity=3)
        self.assertEqual(
            PlanMaterial.objects.filter(est_worksheet=ws, plan_task__isnull=True).count(),
            3,
        )


class GenerateMaterialsForJobMultiInstanceTest(TestCase):
    """Gap 5: generate_materials_for_job multi-instance replication."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='gmi', code='GMI1')
        self.contact = Contact.objects.create(first_name='Multi', last_name='Inst')
        self.pli = PriceListItem.objects.create(
            code='GMI-I', accounting_category=self.cat, is_inventoried=True,
        )

    def test_quantity_multiplies_generation(self):
        """generate_materials_for_job with quantity=3 should create 3 Material rows."""
        from apps.jobs.services import JobService
        from apps.inventory.models import Material
        wt = WorkTemplate.objects.create(
            template_name='gmi-wt', base_price=Decimal('0'), is_active=True,
        )
        TemplateMaterial.objects.create(
            work_template=wt, description='bolt',
            quantity=Decimal('10'), price_list_item=self.pli,
        )
        job = Job.objects.create(job_number='JOB-GMI-1', contact=self.contact)
        wt.generate_materials_for_job(job, quantity=3)
        mats = Material.objects.filter(job=job, task__isnull=True)
        self.assertEqual(mats.count(), 3,
                         'generate_materials_for_job(quantity=3) should create 3 Material rows')
        # Each has qty=10; total earmark should be 3*10=30
        e = Earmark.objects.get(price_list_item=self.pli, job=job)
        self.assertEqual(e.quantity, Decimal('30'),
                         'Earmark quantity should be 3 * 10 = 30')


class TemplateEditDoesNotRetroactTest(TestCase):
    """Gap 6: editing a TemplateMaterial after population must NOT mutate existing PlanMaterials."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name='Retroact', last_name='Test')

    def test_template_material_edit_does_not_change_existing_plan_materials(self):
        wt = WorkTemplate.objects.create(
            template_name='retroact-wt', base_price=Decimal('0'), is_active=True,
        )
        tm = TemplateMaterial.objects.create(
            work_template=wt, description='original desc', quantity=Decimal('5'),
        )
        job = Job.objects.create(job_number='JOB-RET-1', contact=self.contact)
        ws = EstWorksheet.objects.create(job=job)
        # Populate worksheet from template
        wt.generate_materials_for_worksheet(ws, quantity=1)
        pms_before = list(PlanMaterial.objects.filter(est_worksheet=ws))
        self.assertEqual(len(pms_before), 1)
        original_desc = pms_before[0].description

        # Mutate the template material
        tm.description = 'changed desc'
        tm.save()

        # Re-query existing PlanMaterial rows — must be unchanged
        pm = PlanMaterial.objects.get(pk=pms_before[0].pk)
        self.assertEqual(pm.description, original_desc,
                         'Editing TemplateMaterial must not retroactively alter populated PlanMaterials')


class GenerateMaterialsForJobTest(TestCase):
    def test_populate_from_template_creates_taskless_materials_with_earmarks(self):
        from apps.jobs.services import JobService
        from apps.inventory.models import Material, Earmark, PriceListItem
        from apps.core.models import AccountingCategory
        from apps.contacts.models import Contact
        contact = Contact.objects.create(first_name='Test', last_name='User')
        cat = AccountingCategory.objects.create(name='c', code='GJ1')
        pli = PriceListItem.objects.create(
            code='I-GJ', accounting_category=cat, is_inventoried=True,
        )
        wt = WorkTemplate.objects.create(
            template_name='t-gj', base_price=Decimal('0'), is_active=True,
        )
        TemplateMaterial.objects.create(
            work_template=wt, description='x',
            quantity=Decimal('4'), price_list_item=pli,
        )
        job = Job.objects.create(job_number='JOB-GJ-1', contact=contact)
        JobService.populate_from_template(job, wt)
        mats = Material.objects.filter(job=job, task__isnull=True)
        self.assertEqual(mats.count(), 1)
        e = Earmark.objects.get(price_list_item=pli, job=job)
        self.assertEqual(e.quantity, Decimal('4'))
