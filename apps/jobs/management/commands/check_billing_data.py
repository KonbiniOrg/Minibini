from django.core.management.base import BaseCommand
from apps.jobs.models import RateScheme, PlanTask, Task, TaskCharge
from apps.estimates.models import TaskTemplate


class Command(BaseCommand):
    help = 'Read-only diagnostic: report rows that will not survive Phase B constraints.'

    def handle(self, *args, **options):
        issues = []

        # RateScheme.accounting_category will become NOT NULL in Phase B
        ratescheme_no_ac = RateScheme.objects.filter(accounting_category__isnull=True)
        if ratescheme_no_ac.exists():
            issues.append(
                f'{ratescheme_no_ac.count()} RateScheme(s) without accounting_category: '
                f'{list(ratescheme_no_ac.values_list("rate_scheme_id", "name"))}'
            )

        # PlanTask.rate_scheme will become NOT NULL
        planTask_no_scheme = PlanTask.objects.filter(rate_scheme__isnull=True)
        if planTask_no_scheme.exists():
            issues.append(
                f'{planTask_no_scheme.count()} PlanTask(s) without rate_scheme: '
                f'{list(planTask_no_scheme.values_list("plan_task_id", "name"))}'
            )

        # PlanTask.est_qty will become NOT NULL
        planTask_no_qty = PlanTask.objects.filter(est_qty__isnull=True)
        if planTask_no_qty.exists():
            issues.append(
                f'{planTask_no_qty.count()} PlanTask(s) without est_qty: '
                f'{list(planTask_no_qty.values_list("plan_task_id", "name"))}'
            )

        # TaskTemplate.rate_scheme + default_billable_qty NOT NULL
        tt_no_scheme = TaskTemplate.objects.filter(rate_scheme__isnull=True)
        if tt_no_scheme.exists():
            issues.append(
                f'{tt_no_scheme.count()} TaskTemplate(s) without rate_scheme: '
                f'{list(tt_no_scheme.values_list("template_id", "template_name"))}'
            )
        tt_no_qty = TaskTemplate.objects.filter(default_billable_qty__isnull=True)
        if tt_no_qty.exists():
            issues.append(
                f'{tt_no_qty.count()} TaskTemplate(s) without default_billable_qty: '
                f'{list(tt_no_qty.values_list("template_id", "template_name"))}'
            )

        # Every Task must have a TaskCharge
        tasks_no_charge = Task.objects.filter(charge__isnull=True)
        if tasks_no_charge.exists():
            sample = list(tasks_no_charge.values_list("task_id", "name")[:20])
            ellipsis = "..." if tasks_no_charge.count() > 20 else ""
            issues.append(
                f'{tasks_no_charge.count()} Task(s) without TaskCharge: '
                f'{sample}{ellipsis}'
            )

        # AC mismatches between work item and scheme (informational)
        for pt in PlanTask.objects.filter(rate_scheme__isnull=False):
            if pt.accounting_category_id and pt.accounting_category_id != pt.rate_scheme.accounting_category_id:
                issues.append(
                    f'PlanTask {pt.pk} ({pt.name}): AC differs from scheme — '
                    f'pt.AC={pt.accounting_category_id}, scheme.AC={pt.rate_scheme.accounting_category_id}'
                )

        if not issues:
            self.stdout.write(self.style.SUCCESS('All clear — dev DB is ready for Phase B.'))
        else:
            self.stdout.write(self.style.WARNING('Issues found — fix before Phase B:'))
            for issue in issues:
                self.stdout.write(f'  - {issue}')
