import datetime
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required, permission_required

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from intuitlib.client import AuthClient
from intuitlib.enums import Scopes

from apps.api.permissions import CanManageConfig
from apps.qbo.models import QBOConnection


# --- OAuth browser-redirect endpoints (not DRF) ---
# These use Django decorators because they involve browser redirects,
# not XHR calls from the SPA.

@login_required
@permission_required('core.can_manage_config', raise_exception=True)
@require_GET
def qbo_connect(request):
    """Initiate OAuth flow — redirect to Intuit authorization page."""
    auth_client = AuthClient(
        client_id=settings.QBO_CLIENT_ID,
        client_secret=settings.QBO_CLIENT_SECRET,
        redirect_uri=settings.QBO_REDIRECT_URI,
        environment=settings.QBO_ENVIRONMENT,
    )
    url = auth_client.get_authorization_url(scopes=[Scopes.ACCOUNTING])
    request.session['qbo_csrf_token'] = auth_client.state_token
    return redirect(url)


@login_required
@permission_required('core.can_manage_config', raise_exception=True)
@require_GET
def qbo_callback(request):
    """OAuth callback — exchange code for tokens and store connection."""
    auth_code = request.GET.get('code')
    realm_id = request.GET.get('realmId')
    state = request.GET.get('state')

    if not auth_code or not realm_id:
        return JsonResponse({'error': 'Missing code or realmId'}, status=400)

    # Validate CSRF state token to prevent OAuth CSRF attacks
    if state != request.session.get('qbo_csrf_token'):
        return JsonResponse({'error': 'Invalid state token'}, status=400)

    auth_client = AuthClient(
        client_id=settings.QBO_CLIENT_ID,
        client_secret=settings.QBO_CLIENT_SECRET,
        redirect_uri=settings.QBO_REDIRECT_URI,
        environment=settings.QBO_ENVIRONMENT,
    )
    auth_client.get_bearer_token(auth_code, realm_id=realm_id)

    now = timezone.now()

    # Deactivate any existing connections
    QBOConnection.objects.filter(is_active=True).update(is_active=False)

    QBOConnection.objects.create(
        realm_id=realm_id,
        access_token=auth_client.access_token,
        refresh_token=auth_client.refresh_token,
        access_token_expires_at=now + datetime.timedelta(hours=1),
        refresh_token_expires_at=now + datetime.timedelta(days=100),
        is_active=True,
        connected_at=now,
    )

    # Redirect to SPA settings page
    return redirect('/#/settings')


# --- DRF API endpoints (called by SPA via XHR) ---

@api_view(['GET'])
@permission_classes([IsAuthenticated, CanManageConfig])
def qbo_status(request):
    """Return current QBO connection status."""
    conn = QBOConnection.objects.filter(is_active=True).first()
    if not conn:
        return Response({'status': 'not_connected'})

    return Response({
        'status': 'connected',
        'realm_id': conn.realm_id,
        'connected_at': conn.connected_at.isoformat(),
        'last_sync_at': conn.last_sync_at.isoformat() if conn.last_sync_at else None,
        'refresh_token_expiring_soon': conn.is_refresh_token_expiring_soon,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated, CanManageConfig])
def qbo_disconnect(request):
    """Disconnect from QBO — deactivate the active connection."""
    QBOConnection.objects.filter(is_active=True).update(is_active=False)
    return Response({'status': 'disconnected'})
