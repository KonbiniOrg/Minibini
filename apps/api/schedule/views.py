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
    data = ScheduleService.get_schedule(now=timezone.now(), horizon_days=days)
    return Response(data)
