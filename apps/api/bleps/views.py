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
    queryset = Blep.objects.all().order_by('-start_time')
    serializer_class = BlepSerializer
    permission_classes = [IsAuthenticated]
