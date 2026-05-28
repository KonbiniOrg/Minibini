from django.db import transaction
from django.utils import timezone

from apps.core.management.base import ScheduledProcessCommand
from apps.core.models import HistoryEntry, User
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import ChangeOrder


class Command(ScheduledProcessCommand):
    help = 'Expire open change orders whose expiration_date has passed.'
    process_name = 'mark_change_orders_expired'

    def run(self):
        now = timezone.now()
        skipped_no_expiry = ChangeOrder.objects.filter(
            status=ChangeOrder.STATUS_OPEN, expiration_date__isnull=True,
        ).count()
        due_pks = list(
            ChangeOrder.objects.filter(
                status=ChangeOrder.STATUS_OPEN,
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
                    co = ChangeOrder.objects.select_for_update().get(pk=pk)
                    if co.status != ChangeOrder.STATUS_OPEN:
                        continue
                    days = self._validity_days(co)
                    ChangeOrderService.update_status(pk, ChangeOrder.STATUS_EXPIRED)
                    HistoryEntry.objects.create(
                        entry_type='action', object_type='change_order', object_id=pk,
                        user=system_user,
                        changes={
                            'status': {'old': ChangeOrder.STATUS_OPEN, 'new': ChangeOrder.STATUS_EXPIRED},
                            '_action': f'Auto-expired (valid {days} days)' if days is not None else 'Auto-expired',
                        },
                    )
                    expired += 1
            except Exception as exc:  # noqa: BLE001 - record per-CO failures, keep sweeping
                errors.append(f'ChangeOrder {pk}: {exc}')

        return {'expired': expired, 'skipped_no_expiry': skipped_no_expiry, 'errors': errors}

    @staticmethod
    def _validity_days(co):
        if co.sent_date and co.expiration_date:
            return (co.expiration_date - co.sent_date).days
        return None
