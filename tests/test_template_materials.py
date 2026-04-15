from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.estimates.models import WorkTemplate, EstWorksheet
from apps.inventory.models import TemplateMaterial, PlanMaterial


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
