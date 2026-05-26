from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.api.mixins import LineItemMixin, StatusTransitionMixin
from apps.api.permissions import CanManageJobs
from apps.core.services import NotFoundError
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import ChangeOrder, ChangeOrderLineItem

from .serializers import ChangeOrderLineItemSerializer, ChangeOrderSerializer


class ChangeOrderViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = ChangeOrder.objects.all().order_by('-created_date')
    serializer_class = ChangeOrderSerializer
    lookup_field = 'pk'

    # LineItemMixin config
    line_item_serializer_class = ChangeOrderLineItemSerializer
    line_item_parent_field = 'change_order'
    line_item_service_class = ChangeOrderService

    # StatusTransitionMixin: mark-open is the only status action registered
    # through the mixin. For the general status PATCH we override perform_update
    # to route through ChangeOrderService.update_status.
    status_actions = {
        'mark-open': {'service': ChangeOrderService.mark_open},
    }

    def get_permissions(self):
        read_actions = ('list', 'retrieve')
        if self.action in read_actions:
            return [IsAuthenticated()]
        if self.action == 'line_items' and self.request.method == 'GET':
            return [IsAuthenticated()]
        if self.action == 'line_item_detail' and self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageJobs()]

    def get_queryset(self):
        qs = super().get_queryset()
        job = self.request.query_params.get('job')
        if job:
            qs = qs.filter(job_id=job)
        return qs

    def perform_create(self, serializer):
        data = serializer.initial_data
        job_id = data.get('job')
        try:
            co = ChangeOrderService.create(job_id=job_id)
        except DjangoValidationError as e:
            from rest_framework.exceptions import ValidationError as DRFValidationError
            msg = e.messages[0] if hasattr(e, 'messages') else str(e)
            raise DRFValidationError({'detail': msg})
        except NotFoundError as e:
            from rest_framework.exceptions import NotFound
            raise NotFound(str(e))
        serializer.instance = co

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        # We don't call serializer.is_valid() with the normal mandatory-field
        # checks because the serializer has read-only fields (estimate, etc.)
        # that only exist after the service runs. Instead, delegate directly.
        try:
            co = ChangeOrderService.create(job_id=request.data.get('job'))
        except DjangoValidationError as e:
            msg = e.messages[0] if hasattr(e, 'messages') else str(e)
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)
        except NotFoundError as e:
            return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(co)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        """Route status changes through ChangeOrderService.update_status."""
        new_status = serializer.validated_data.get('status')
        instance = serializer.instance
        if new_status and new_status != instance.status:
            try:
                updated = ChangeOrderService.update_status(instance.pk, new_status)
            except DjangoValidationError as e:
                from rest_framework.exceptions import ValidationError as DRFValidationError
                msg = e.messages[0] if hasattr(e, 'messages') else str(e)
                raise DRFValidationError({'detail': msg})
            except NotFoundError as e:
                from rest_framework.exceptions import NotFound
                raise NotFound(str(e))
            serializer.instance = updated
        else:
            serializer.save()

    def destroy(self, request, *args, **kwargs):
        co = self.get_object()
        try:
            ChangeOrderService.discard_draft(co.pk)
        except DjangoValidationError as e:
            msg = e.messages[0] if hasattr(e, 'messages') else str(e)
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)
        except NotFoundError as e:
            return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response({'message': 'Change order discarded.'})

    @action(detail=True, methods=['post'], url_path='seed-new', url_name='seed-new')
    def seed_new(self, request, pk=None):
        """Create a new draft CO by copying all line items from an existing CO."""
        try:
            new_co = ChangeOrderService.seed_new(pk)
        except NotFoundError as e:
            return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
        except DjangoValidationError as e:
            msg = e.messages[0] if hasattr(e, 'messages') else str(e)
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.get_serializer(new_co)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
