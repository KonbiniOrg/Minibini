from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone

from apps.schedule.services import ScheduleService


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def schedule_view(request):
    raw_days = request.query_params.get('days')
    days = None
    if raw_days is not None:
        try:
            days = int(raw_days)
        except (TypeError, ValueError):
            days = None

    # Working-day offset for past/future scrolling. Clamped to keep the
    # window within a sane range either side of today.
    offset = 0
    raw_offset = request.query_params.get('offset')
    if raw_offset is not None:
        try:
            offset = max(-60, min(60, int(raw_offset)))
        except (TypeError, ValueError):
            offset = 0

    data = ScheduleService.get_schedule(
        now=timezone.now(), horizon_days=days, offset=offset,
    )
    return Response(data)
