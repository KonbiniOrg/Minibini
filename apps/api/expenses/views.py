from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.expenses.models import Expense
from apps.expenses.services import ExpenseService
from apps.api.mixins import QBORetrySyncMixin
from apps.api.permissions import CanManageFinancials
from apps.api.history.serializers import HistoryEntrySerializer
from apps.core.models import ExpensesHistory
from .serializers import ExpenseSerializer


class ExpenseViewSet(QBORetrySyncMixin, viewsets.ModelViewSet):
    retry_deleted_message = 'Expense deleted.'

    def retry_service_call(self, obj, request):
        return ExpenseService.retry_sync(expense=obj, actor=request.user)

    queryset = Expense.objects.all().select_related(
        'entered_by', 'purchased_by', 'accounting_category',
        'job', 'material', 'material__job', 'reimbursement',
    )
    serializer_class = ExpenseSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'create', 'history'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageFinancials()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.has_perm('core.can_manage_financials'):
            qs = qs.filter(purchased_by=user)

        params = self.request.query_params
        if params.get('purchased_by'):
            qs = qs.filter(purchased_by=params['purchased_by'])
        if params.get('status'):
            qs = qs.filter(status=params['status'])
        if params.get('qbo_sync_status'):
            qs = qs.filter(qbo_sync_status=params['qbo_sync_status'])
        if params.get('payment_method'):
            qs = qs.filter(payment_method=params['payment_method'])
        if params.get('accounting_category'):
            qs = qs.filter(accounting_category=params['accounting_category'])
        if params.get('job'):
            qs = qs.filter(job=params['job'])
        if params.get('from'):
            qs = qs.filter(purchased_on__gte=params['from'])
        if params.get('to'):
            qs = qs.filter(purchased_on__lte=params['to'])
        return qs

    def _claims_context_for(self, expenses):
        from apps.invoicing.claims import InvoiceClaimService
        pks = [e.pk for e in expenses]
        return InvoiceClaimService.claims_for_atoms('expense', pks)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        objs = page if page is not None else list(queryset)
        ctx = {**self.get_serializer_context(),
               'invoice_claims': self._claims_context_for(objs)}
        serializer = self.get_serializer(objs, many=True, context=ctx)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        ctx = {**self.get_serializer_context(),
               'invoice_claims': self._claims_context_for([instance])}
        return Response(self.get_serializer(instance, context=ctx).data)

    def perform_create(self, serializer):
        data = serializer.validated_data.copy()
        purchased_by = data.pop('purchased_by', None)
        new_material = data.pop('new_material', None)
        # Expenses no longer link an existing material; ignore any inbound id.
        data.pop('material', None)
        try:
            expense = ExpenseService.submit(
                entered_by=self.request.user,
                purchased_by=purchased_by,
                new_material=new_material,
                **data,
            )
        except DjangoValidationError as e:
            raise self._to_drf_validation_error(e)
        serializer.instance = expense

    def perform_update(self, serializer):
        # Mutate serializer.instance (not a fresh get_object()) so the serialized
        # response reflects the change the service applied.
        try:
            ExpenseService.update(
                expense=serializer.instance,
                actor=self.request.user,
                **serializer.validated_data,
            )
        except DjangoValidationError as e:
            raise self._to_drf_validation_error(e)

    def destroy(self, request, *args, **kwargs):
        expense = self.get_object()
        try:
            ExpenseService.delete(expense=expense, actor=request.user)
        except DjangoValidationError as e:
            return Response({'detail': e.messages[0]}, status=400)
        return Response({'message': 'Expense deleted.'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='history', url_name='history')
    def history(self, request, pk=None):
        expense = self.get_object()
        entries = ExpensesHistory.objects.filter(
            object_type='expense', object_id=expense.pk,
        ).select_related('user').order_by('-timestamp')
        page = self.paginate_queryset(entries)
        if page is not None:
            serializer = HistoryEntrySerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = HistoryEntrySerializer(entries, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='reject', url_name='reject')
    def reject(self, request, pk=None):
        expense = self.get_object()
        try:
            ExpenseService.reject(expense=expense, actor=request.user)
        except DjangoValidationError as e:
            return Response({'detail': e.messages[0]}, status=400)
        serializer = self.get_serializer(expense)
        return Response(serializer.data)

    @staticmethod
    def _to_drf_validation_error(django_error):
        from rest_framework.exceptions import ValidationError as DRFValidationError
        if hasattr(django_error, 'message_dict'):
            return DRFValidationError(django_error.message_dict)
        return DRFValidationError({'detail': django_error.messages})
