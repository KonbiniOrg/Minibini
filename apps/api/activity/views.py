from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.activity.services import ActivityService


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def activity_view(request):
    return Response(ActivityService.get_activity())
