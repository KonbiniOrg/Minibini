from django.db import transaction
from apps.core.history import record_history
from django.utils import timezone

from apps.core.management.base import ScheduledProcessCommand
from apps.core.models import User
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateService


class Command(ScheduledProcessCommand):
    help = 'Expire open estimates whose expiration_date has passed.'
    process_name = 'mark_estimates_expired'

    def run(self):
        now = timezone.now()
        skipped_no_expiry = Estimate.objects.filter(
            status=Estimate.STATUS_OPEN, expiration_date__isnull=True,
        ).count()
        due_pks = list(
            Estimate.objects.filter(
                status=Estimate.STATUS_OPEN,
                expiration_date__isnull=False,
                expiration_date__lte=now,
            ).values_list('pk', flat=True)
        )
        system_user, _ = User.objects.get_or_create(
            username='system', defaults={'first_name': 'System', 'is_active': False},
        )

        expired = 0
        errors = []
        for pk in due_pks:
            try:
                with transaction.atomic():
                    est = Estimate.objects.select_for_update().get(pk=pk)
                    if est.status != Estimate.STATUS_OPEN:
                        continue
                    days = self._validity_days(est)
                    EstimateService.update_status(pk, Estimate.STATUS_EXPIRED)
                    record_history(
                        entry_type='action', object_type='estimate', object_id=pk,
                        user=system_user,
                        changes={
                            'status': {'old': Estimate.STATUS_OPEN, 'new': Estimate.STATUS_EXPIRED},
                            '_action': f'Auto-expired (valid {days} days)' if days is not None else 'Auto-expired',
                        },
                    )
                    expired += 1
            except Exception as exc:  # noqa: BLE001 - record per-estimate failures, keep sweeping
                errors.append(f'Estimate {pk}: {exc}')

        return {'expired': expired, 'skipped_no_expiry': skipped_no_expiry, 'errors': errors}

    @staticmethod
    def _validity_days(est):
        if est.sent_date and est.expiration_date:
            return (est.expiration_date - est.sent_date).days
        return None
