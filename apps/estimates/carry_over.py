"""Atom carry-over from Worksheet/Estimate to Job at acceptance time.

Triggered automatically when an Estimate transitions to ACCEPTED. Walks the
worksheet's atoms (PlanTasks, PlanMaterials) and creates matching atoms on
the Job (Tasks/TaskCharges, Materials). For direct-estimate line items with
template refs (no worksheet), creates equivalent atoms from the templates.
Idempotent:
  - Worksheet path: keyed on Task.source_plan_task (OneToOne FK)
  - Direct line item path: keyed on Task.source_template / Material.price_list_item
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

        # Phase A: walk worksheet atoms (if a worksheet exists)
        worksheet = estimate.worksheets.first()
        if worksheet:
            tasks_created += AtomCarryOverService._carry_over_plan_tasks(worksheet, job)
            materials_created += AtomCarryOverService._carry_over_plan_materials(worksheet, job)

        # Phase B: walk direct-estimate line items with template refs
        for li in estimate.estimatelineitem_set.all():
            if li.source_template_id and not li.sources.exists():
                if AtomCarryOverService._create_task_from_line_item(li, job):
                    tasks_created += 1
            elif li.price_list_item_id and not li.sources.exists():
                if AtomCarryOverService._create_material_from_line_item(li, job):
                    materials_created += 1

        return {'tasks_created': tasks_created, 'materials_created': materials_created}

    @staticmethod
    def _carry_over_plan_tasks(worksheet, job):
        from apps.jobs.models import PlanTask, Task, copy_active_modifiers
        count = 0
        for pt in PlanTask.objects.filter(
            est_worksheet=worksheet,
        ).select_related('rate_scheme'):
            if Task.objects.filter(job=job, source_plan_task=pt).exists():
                continue
            Task.objects.create(
                job=job,
                name=pt.name,
                description=pt.description,
                source_plan_task=pt,
                rate_scheme=pt.rate_scheme,
                active_modifiers=copy_active_modifiers(pt.active_modifiers),
                est_qty=pt.est_qty,
                est_worker_time=pt.est_worker_time,
                actual_qty=None,
            )
            count += 1
        return count

    @staticmethod
    def _carry_over_plan_materials(worksheet, job):
        from apps.inventory.models import Material, PlanMaterial
        from apps.jobs.models import Task
        count = 0
        for pm in PlanMaterial.objects.filter(est_worksheet=worksheet):
            # Idempotency: skip if a Material already exists that came from this PlanMaterial
            if Material.objects.filter(job=job, source_plan_material=pm).exists():
                continue
            # If the PlanMaterial was attached to a PlanTask, find the corresponding Task on the job
            task = None
            if pm.plan_task_id:
                task = Task.objects.filter(job=job, source_plan_task=pm.plan_task).first()
            Material.objects.create(
                job=job,
                task=task,
                description=pm.description,
                quantity=pm.quantity,
                unit_cost=pm.unit_cost,
                sell_price=pm.sell_price,
                price_list_item=pm.price_list_item,
                accounting_category=pm.accounting_category,
                source_plan_material=pm,
            )
            count += 1
        return count

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
            rate_scheme=template.rate_scheme,
            active_modifiers=copy_active_modifiers(template.default_active_modifiers),
            est_qty=line_item.qty,
            est_worker_time=None,
            actual_qty=None,
        )
        return True

    @staticmethod
    def _create_material_from_line_item(line_item, job):
        from apps.inventory.models import Material
        pli = line_item.price_list_item
        if Material.objects.filter(job=job, price_list_item=pli).exists():
            return False
        Material.objects.create(
            job=job,
            description=pli.description,
            quantity=line_item.qty,
            unit_cost=pli.purchase_price,
            sell_price=pli.selling_price,
            price_list_item=pli,
            accounting_category=pli.accounting_category,
        )
        return True
