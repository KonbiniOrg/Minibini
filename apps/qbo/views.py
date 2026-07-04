import datetime
from django.conf import settings
from django.db import transaction
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

from apps.api.permissions import CanManageConfig, CanManageFinancials
from apps.qbo.models import QBOConnection
from apps.qbo.services import QBOAccountsService, QBOExpenseSyncService, QBOSyncFailureService


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

    del request.session['qbo_csrf_token']

    auth_client = AuthClient(
        client_id=settings.QBO_CLIENT_ID,
        client_secret=settings.QBO_CLIENT_SECRET,
        redirect_uri=settings.QBO_REDIRECT_URI,
        environment=settings.QBO_ENVIRONMENT,
    )
    auth_client.get_bearer_token(auth_code, realm_id=realm_id)

    now = timezone.now()

    with transaction.atomic():
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
    return redirect(f'{settings.SPA_BASE_URL}/#/settings')


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


@api_view(['GET'])
@permission_classes([IsAuthenticated, CanManageConfig])
def qbo_accounts(request):
    """Return QBO Items and expense accounts for category mapping."""
    try:
        items = QBOAccountsService.get_income_items()
        expense = QBOAccountsService.get_expense_accounts()
        return Response({
            'income_items': items,
            'expense_accounts': expense,
        })
    except ValueError as e:
        return Response({'error': str(e)}, status=400)


@api_view(['GET'])
@permission_classes([IsAuthenticated, CanManageConfig])
def qbo_payment_accounts(request):
    """Return Bank, Credit Card, and Other Current Asset accounts from QBO."""
    try:
        accounts = QBOExpenseSyncService.get_payment_accounts()
        return Response({'payment_accounts': accounts})
    except ValueError as e:
        return Response({'error': str(e)}, status=400)


@api_view(['GET'])
@permission_classes([IsAuthenticated, CanManageFinancials])
def qbo_sync_failures(request):
    """Return all sync-failed records across Expense, Reimbursement, BillPayment."""
    return Response({'failures': QBOSyncFailureService.list_failures()})


@api_view(['POST'])
@permission_classes([IsAuthenticated, CanManageFinancials])
def qbo_sync_failures_retry_all(request):
    """Retry every sync-failed record; returns {retried, still_failing}."""
    from apps.expenses.models import Expense, Reimbursement
    from apps.purchasing.models import BillPayment
    from apps.expenses.services import ExpenseService, ReimbursementService
    from apps.purchasing.services import BillPaymentService

    failures = QBOSyncFailureService.list_failures()
    attempted = 0

    for item in failures:
        attempted += 1
        entity_type = item['entity_type']
        pk = item['id']
        try:
            if entity_type == 'expense':
                expense = Expense.objects.get(pk=pk)
                ExpenseService.retry(expense=expense, actor=request.user)
            elif entity_type == 'reimbursement':
                batch = Reimbursement.objects.get(pk=pk)
                ReimbursementService.retry(batch=batch, actor=request.user)
            elif entity_type == 'bill_payment':
                BillPaymentService.retry(pk)
        except Exception:  # noqa: BLE001 — one failure must not abort the loop
            pass

    # Re-query each record to count how many are still failing.
    still_failing = 0
    for item in failures:
        entity_type = item['entity_type']
        pk = item['id']
        try:
            if entity_type == 'expense':
                obj = Expense.objects.get(pk=pk)
                if obj.qbo_sync_status == Expense.SYNC_FAILED:
                    still_failing += 1
            elif entity_type == 'reimbursement':
                obj = Reimbursement.objects.get(pk=pk)
                if obj.qbo_sync_status == Reimbursement.SYNC_FAILED:
                    still_failing += 1
            elif entity_type == 'bill_payment':
                obj = BillPayment.objects.get(pk=pk)
                if obj.qbo_sync_status == BillPayment.SYNC_FAILED:
                    still_failing += 1
        except Exception:  # noqa: BLE001 — deleted record = resolved
            pass

    return Response({'retried': attempted, 'still_failing': still_failing})
