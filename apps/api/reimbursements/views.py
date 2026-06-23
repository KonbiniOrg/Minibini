from decimal import Decimal
from collections import defaultdict

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth import get_user_model

from apps.expenses.models import Expense, Reimbursement
from apps.expenses.services import ReimbursementService
from apps.api.mixins import ConfirmDeleteMixin
from apps.api.permissions import CanManageFinancials
from .serializers import ReimbursementSerializer, ReimbursementCreateSerializer

User = get_user_model()


class ReimbursementViewSet(ConfirmDeleteMixin, viewsets.ModelViewSet):
    queryset = Reimbursement.objects.all().select_related(
        'purchased_by', 'created_by',
    ).prefetch_related('expenses')
    serializer_class = ReimbursementSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        return [IsAuthenticated(), CanManageFinancials()]

    def get_queryset(self):
        qs = super().get_queryset()
        pb = self.request.query_params.get('purchased_by')
        if pb:
            qs = qs.filter(purchased_by=pb)
        return qs

    def create(self, request, *args, **kwargs):
        input_ser = ReimbursementCreateSerializer(data=request.data)
        input_ser.is_valid(raise_exception=True)
        data = input_ser.validated_data
        try:
            batch = ReimbursementService.create_batch(
                purchased_by=data['purchased_by'],
                expense_ids=data['expense_ids'],
                paid_on=data['paid_on'],
                payment_account_id=data['payment_account_id'],
                reference_number=data.get('reference_number', ''),
                notes=data.get('notes', ''),
                created_by=request.user,
            )
        except DjangoValidationError as e:
            from rest_framework.exceptions import ValidationError as DRFValidationError
            raise DRFValidationError(
                e.message_dict if hasattr(e, 'message_dict') else {'detail': e.messages}
            )
        return Response(
            ReimbursementSerializer(batch).data,
            status=status.HTTP_201_CREATED,
        )

    def get_deletion_impact(self, batch):
        return {
            'expense_count': batch.expenses.count(),
            'qbo_void_required': bool(batch.qbo_id),
            'message': (
                f"This will unwind the batch: {batch.expenses.count()} "
                f"expenses flipped back to submitted"
                + (", QBO Purchase voided" if batch.qbo_id else "")
                + ". Confirm with ?confirm=true."
            ),
        }

    def perform_confirmed_destroy(self, batch):
        try:
            ReimbursementService.delete(batch=batch, actor=self.request.user)
        except DjangoValidationError as e:
            return Response({'detail': e.messages[0]}, status=400)
        return Response({'message': 'Reimbursement batch deleted.'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='retry-sync', url_name='retry-sync')
    def retry_sync(self, request, pk=None):
        batch = self.get_object()
        try:
            result = ReimbursementService.retry_sync(batch=batch, actor=request.user)
        except DjangoValidationError as e:
            return Response({'detail': e.messages[0]}, status=400)
        if result is None:  # delete branch completed — the batch was removed
            return Response({'message': 'Reimbursement batch deleted.'})
        batch.refresh_from_db()
        return Response(ReimbursementSerializer(batch).data)

    @action(
        detail=False, methods=['get'],
        url_path='outstanding-summary', url_name='outstanding-summary',
    )
    def outstanding_summary(self, request):
        qs = Expense.objects.filter(
            status=Expense.STATUS_SUBMITTED,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
        ).select_related('purchased_by').order_by('purchased_on')

        buckets = defaultdict(lambda: {
            'count': 0,
            'total': Decimal('0'),
            'oldest_purchased_on': None,
        })
        for e in qs:
            if not e.purchased_by_id:
                continue
            row = buckets[e.purchased_by_id]
            row['count'] += 1
            row['total'] += e.amount
            if row['oldest_purchased_on'] is None or e.purchased_on < row['oldest_purchased_on']:
                row['oldest_purchased_on'] = e.purchased_on

        users = []
        for user_id, data in sorted(buckets.items(), key=lambda kv: -kv[1]['total']):
            user = User.objects.filter(pk=user_id).first()
            users.append({
                'purchased_by': user_id,
                'username': user.username if user else '',
                'full_name': (user.get_full_name() if user else '') or (user.username if user else ''),
                'count': data['count'],
                'total': str(data['total']),
                'oldest_purchased_on': (
                    data['oldest_purchased_on'].isoformat()
                    if data['oldest_purchased_on'] else None
                ),
            })
        return Response({'users': users})
