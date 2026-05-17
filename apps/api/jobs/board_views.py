from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.api.permissions import CanManageJobs
from apps.jobs.models import Task
from apps.jobs.services import BoardService


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pipeline_view(request):
    data = BoardService.get_pipeline_data()
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def approved_view(request):
    data = BoardService.get_approved_data()
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def unpaid_view(request):
    data = BoardService.get_unpaid_data()
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def closed_view(request):
    data = BoardService.get_closed_data()
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def board_view(request):
    """Return all data needed to render the job board."""
    data = BoardService.get_board_data()
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def task_reorder_view(request):
    """Bulk update worker_queue for a list of task IDs.

    Expects: {"task_ids": [3, 1, 2]}
    Sets worker_queue = 1, 2, 3 in the order provided.

    Any authenticated user may call this endpoint. Workers use it to
    rearrange their own queue on the home page; managers use it on the
    job board. No ownership check is performed.
    """
    task_ids = request.data.get('task_ids', [])
    if not task_ids or not isinstance(task_ids, list):
        return Response({'error': 'task_ids must be a non-empty list'}, status=400)

    for position, task_id in enumerate(task_ids, start=1):
        Task.objects.filter(pk=task_id).update(worker_queue=position)

    return Response({'status': 'ok'})


@api_view(['POST'])
@permission_classes([IsAuthenticated, CanManageJobs])
def task_assign_view(request, task_pk):
    """Assign a task to a worker and set queue position.

    Expects: {"assignee": user_id, "worker_queue": position}
    Optionally: {"est_worker_time": "PT1H30M"} — an estimated worker time to
    set alongside the assignment. Assigning a task with no estimate (and no
    est_worker_time supplied) returns {"needs_worker_time": true} so the UI
    can prompt. Pass assignee: null to unassign.
    """
    from datetime import timedelta
    from django.utils.dateparse import parse_duration
    from apps.jobs.services import TaskService, TaskWorkerTimeRequired

    task = Task.objects.filter(pk=task_pk).first()
    if not task:
        return Response({'error': 'Task not found'}, status=404)

    assignee_id = request.data.get('assignee')
    worker_queue = request.data.get('worker_queue')

    raw_ewt = request.data.get('est_worker_time')
    est_worker_time = None
    if raw_ewt not in (None, ''):
        est_worker_time = parse_duration(str(raw_ewt))
        if est_worker_time is None or est_worker_time <= timedelta(0):
            return Response(
                {'est_worker_time': ['Enter a duration greater than zero.']},
                status=400,
            )

    try:
        TaskService.assign(
            task, assignee_id,
            worker_queue=worker_queue,
            est_worker_time=est_worker_time,
        )
    except TaskWorkerTimeRequired:
        return Response({'needs_worker_time': True})

    return Response({'status': 'ok'})
