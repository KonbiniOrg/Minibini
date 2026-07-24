from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.setup_gates import gate_status


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def setup_status(request):
    """Per-area availability + unlock messages + last QBO pull time.

    Single source of truth for the sidebar's greyed entries / floating
    callouts and the Home Help setup checklist.
    """
    return Response(gate_status())
