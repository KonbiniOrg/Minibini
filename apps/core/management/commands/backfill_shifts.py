from collections import defaultdict
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from apps.core.models import Shift
from apps.jobs.models import Blep
from apps.core.time_integrity import enclosing_shift_for_blep


class Command(BaseCommand):
    help = "Create enclosing Shifts for existing bleps (idempotent). Run before browser testing."

    def handle(self, *args, **opts):
        bleps = (Blep.objects.filter(user__isnull=False, end_time__isnull=False)
                 .select_related('user').order_by('user_id', 'start_time'))
        groups = defaultdict(list)
        for b in bleps:
            if enclosing_shift_for_blep(b.user, b.start_time, b.end_time):
                continue  # already covered — idempotent
            local_date = timezone.localtime(b.start_time).date()
            groups[(b.user_id, local_date)].append(b)

        created = 0
        with transaction.atomic():
            for (user_id, _date), group in groups.items():
                start = min(b.start_time for b in group)
                end = max(b.end_time for b in group)
                Shift.objects.create(user_id=user_id, start_time=start, end_time=end)
                created += 1

        orphan = Blep.objects.filter(user__isnull=True).count()
        open_bleps = Blep.objects.filter(end_time__isnull=True).count()
        self.stdout.write(self.style.SUCCESS(f"Created {created} shift(s)."))
        if orphan:
            self.stdout.write(self.style.WARNING(f"{orphan} blep(s) have no user — not enclosed."))
        if open_bleps:
            self.stdout.write(self.style.WARNING(f"{open_bleps} open blep(s) skipped (no end_time)."))
