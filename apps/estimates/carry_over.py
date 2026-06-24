"""Atom carry-over from Worksheet/Estimate to Job at acceptance time.

Triggered automatically when an Estimate transitions to ACCEPTED. Walks the
worksheet's atoms (PlanTasks, PlanMaterials) and creates matching atoms on
the Job (Tasks/TaskCharges, Materials). For direct-estimate line items with
template refs (no worksheet), creates equivalent atoms from the templates.
Idempotent:
  - Worksheet path: keyed on Task.source_plan_task (OneToOne FK)
  - Direct line item path: keyed on Task.source_template / Material.inventory_item
"""
from django.db import transaction


class AtomCarryOverService:

    @staticmethod
    @transaction.atomic
    def carry_over_for_estimate(estimate):
        """Create atoms on the Job from the estimate's worksheet (if any) and from
        any direct-estimate line items that carry a template ref.

        Returns: {'tasks_created': int, 'materials_created': int}
        """
        job = estimate.job

        tasks_created = 0
        materials_created = 0

        # Phase A: materialize the job's worksheet atoms (if any) via the shared
        # core, which also handles provenance, idempotency, and earmarks.
        from apps.estimates.models import EstWorksheet
        from apps.jobs.services import JobService
        worksheet = (
            EstWorksheet.objects.filter(job_id=job.pk)
            .order_by('-est_worksheet_id')
            .first()
        )
        if worksheet:
            counts = JobService.materialize_worksheet_onto_job(job, worksheet)
            tasks_created += counts['tasks_created']
            materials_created += counts['materials_created']

        # Phase B: walk direct-estimate line items with template refs
        for li in estimate.estimatelineitem_set.all():
            if li.source_template_id and not li.sources.exists():
                if AtomCarryOverService._create_task_from_line_item(li, job):
                    tasks_created += 1
            elif li.inventory_item_id and not li.sources.exists():
                if AtomCarryOverService._create_material_from_line_item(li, job):
                    materials_created += 1

        return {'tasks_created': tasks_created, 'materials_created': materials_created}

    @staticmethod
    def _create_task_from_line_item(line_item, job):
        from apps.jobs.models import Task, copy_active_modifiers
        template = line_item.source_template
        # Idempotency: skip if a Task on the same job already came from this template
        if Task.objects.filter(job=job, source_template=template).exists():
            return False
        Task.objects.create(
            job=job,
            name=template.template_name,
            description=template.description or '',
            source_template=template,
            service_price=template.service_price,
            active_modifiers=copy_active_modifiers(template.default_active_modifiers),
            est_qty=line_item.qty,
            est_worker_time=None,
            actual_qty=None,
        )
        return True

    @staticmethod
    def _create_material_from_line_item(line_item, job):
        from apps.inventory.models import Material
        pli = line_item.inventory_item
        if Material.objects.filter(job=job, inventory_item=pli).exists():
            return False
        Material.objects.create(
            job=job,
            description=pli.description,
            quantity=line_item.qty,
            unit_cost=pli.purchase_price,
            sell_price=pli.selling_price,
            inventory_item=pli,
            accounting_category=pli.accounting_category,
        )
        return True
