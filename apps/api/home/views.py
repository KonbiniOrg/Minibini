from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.home_service import HomeService
from apps.jobs.models import Blep


def _serialize_current_blep(blep):
    from apps.jobs.services import blep_minimum_seconds
    task = blep.task
    job = task.job
    return {
        'id': blep.blep_id,
        'start_time': blep.start_time.isoformat() if blep.start_time else None,
        'blep_minimum_seconds': blep_minimum_seconds(),
        'task': {
            'id': task.pk,
            'name': task.name,
            'description': task.description,
            'status': task.status,
        },
        'job': {
            'id': job.pk,
            'job_number': job.job_number,
            'name': job.name,
        } if job else None,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def current_blep_view(request):
    """Return the requesting user's most recent open Blep, or null.

    An open Blep is one with end_time IS NULL. If the user has multiple
    open Bleps (a pre-existing data-model possibility), the one with the
    most recent start_time wins.
    """
    blep = (
        Blep.objects
        .filter(user=request.user, end_time__isnull=True)
        .select_related('task__job')
        .order_by('-start_time')
        .first()
    )
    if blep is None:
        return JsonResponse(None, safe=False)
    return Response(_serialize_current_blep(blep))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def home_view(request):
    """Return the data needed to render the user's home page.

    Shape: {"assigned_tasks": [...], "recent_jobs": [...]}
    """
    return Response(HomeService.get_home_data(request.user))
