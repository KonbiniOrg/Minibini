from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.expenses.models import Expense
from apps.expenses.services import ExpenseService
from apps.api.permissions import CanManageFinancials
from .serializers import ExpenseSerializer


class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.all().select_related(
        'entered_by', 'purchased_by', 'accounting_category',
        'job', 'material', 'material__job', 'reimbursement',
    )
    serializer_class = ExpenseSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'create'):
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
        ExpenseService.delete(expense=expense, actor=request.user)
        return Response({'message': 'Expense deleted.'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='reject', url_name='reject')
    def reject(self, request, pk=None):
        expense = self.get_object()
        try:
            ExpenseService.reject(expense=expense, actor=request.user)
        except DjangoValidationError as e:
            return Response({'detail': e.messages[0]}, status=400)
        serializer = self.get_serializer(expense)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='retry-sync', url_name='retry-sync')
    def retry_sync(self, request, pk=None):
        expense = self.get_object()
        try:
            ExpenseService.retry_sync(expense=expense, actor=request.user)
        except DjangoValidationError as e:
            return Response({'detail': e.messages[0]}, status=400)
        expense.refresh_from_db()
        serializer = self.get_serializer(expense)
        return Response(serializer.data)

    @staticmethod
    def _to_drf_validation_error(django_error):
        from rest_framework.exceptions import ValidationError as DRFValidationError
        if hasattr(django_error, 'message_dict'):
            return DRFValidationError(django_error.message_dict)
        return DRFValidationError({'detail': django_error.messages})
