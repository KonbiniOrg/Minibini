from django.core.management.base import BaseCommand
from apps.core.models import Shift
from apps.core.timeutils import floor_to_minute
from apps.jobs.models import Blep


class Command(BaseCommand):
    help = "Floor existing Shift and Blep start/end times to the whole minute (idempotent)."

    def handle(self, *args, **opts):
        def needs(dt):
            return dt is not None and (dt.second or dt.microsecond)

        shifts = sum(self._normalize(s) for s in Shift.objects.all())
        bleps = sum(self._normalize(b) for b in Blep.objects.all())
        self.stdout.write(self.style.SUCCESS(
            f"Normalized {shifts} shift(s) and {bleps} blep(s) to minute granularity."))

    def _normalize(self, obj):
        if (obj.start_time and (obj.start_time.second or obj.start_time.microsecond)) or \
           (obj.end_time and (obj.end_time.second or obj.end_time.microsecond)):
            obj.save()   # save() floors both fields
            return 1
        return 0
