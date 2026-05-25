import traceback

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import ScheduledProcessRun


class SkipRun(Exception):
    """Raise inside run() to record a 'skipped' outcome (e.g. no QBO connection)."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class ScheduledProcessCommand(BaseCommand):
    """Base for scheduled commands. Subclasses set `process_name` and implement
    `run()`, returning a JSON-serializable summary dict. Every invocation writes
    one ScheduledProcessRun row."""

    process_name = None

    def run(self):  # pragma: no cover - overridden by subclasses
        raise NotImplementedError

    def handle(self, *args, **options):
        if not self.process_name:
            raise ValueError('ScheduledProcessCommand subclasses must set process_name')

        run = ScheduledProcessRun.objects.create(
            process_name=self.process_name,
            started_at=timezone.now(),
        )
        try:
            summary = self.run() or {}
        except SkipRun as exc:
            run.outcome = ScheduledProcessRun.OUTCOME_SKIPPED
            run.summary = {'reason': exc.reason}
            run.finished_at = timezone.now()
            run.save()
            self.stdout.write(f'{self.process_name}: skipped ({exc.reason})')
            return
        except Exception:
            run.outcome = ScheduledProcessRun.OUTCOME_FAILED
            run.error = traceback.format_exc()
            run.finished_at = timezone.now()
            run.save()
            raise

        run.outcome = ScheduledProcessRun.OUTCOME_OK
        run.summary = summary
        run.finished_at = timezone.now()
        run.save()
        self.stdout.write(f'{self.process_name}: ok {summary}')
