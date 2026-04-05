from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.jobs.models import Blep
from apps.api.bleps.serializers import BlepSerializer


class BlepViewSet(viewsets.ModelViewSet):
    """Top-level Blep (time entry) endpoints.

    List supports filters ?user=me|<id>, ?task=<id>, ?since=<iso>.
    Create/update/delete enforce ownership + 24h window or can_manage_time
    in the service layer (added in later tasks).
    """
    serializer_class = BlepSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Blep.objects.all().order_by('-start_time')
        user_param = self.request.query_params.get('user')
        task_param = self.request.query_params.get('task')
        since_param = self.request.query_params.get('since')
        if user_param:
            if user_param == 'me':
                qs = qs.filter(user=self.request.user)
            else:
                qs = qs.filter(user_id=user_param)
        if task_param:
            qs = qs.filter(task_id=task_param)
        if since_param:
            qs = qs.filter(start_time__gte=since_param)
        return qs
