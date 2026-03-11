from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


def stub_501(endpoint_name):
    """Create a view that returns 501 for unimplemented endpoints."""
    @api_view(['GET', 'POST', 'PATCH', 'DELETE'])
    @permission_classes([IsAuthenticated])
    def view(request, *args, **kwargs):
        return Response(
            {'detail': 'Not yet implemented.', 'endpoint': endpoint_name},
            status=501,
        )
    return view
