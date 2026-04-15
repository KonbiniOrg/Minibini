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
