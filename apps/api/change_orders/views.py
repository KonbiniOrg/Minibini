from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.api.mixins import (
    JobScopedPermissionMixin, LineItemMixin, StatusTransitionMixin,
)
from apps.api.permissions import CanManageJobOrPM
from apps.core.services import NotFoundError
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import ChangeOrder, ChangeOrderLineItem

from .serializers import ChangeOrderLineItemSerializer, ChangeOrderSerializer


class ChangeOrderViewSet(
    JobScopedPermissionMixin, StatusTransitionMixin, LineItemMixin,
    viewsets.ModelViewSet,
):
    queryset = ChangeOrder.objects.all().order_by('-created_date')
    serializer_class = ChangeOrderSerializer
    lookup_field = 'pk'

    # JobScopedPermissionMixin config
    job_object_path = 'job'
    job_create_field = 'job'

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
        read_actions = ('list', 'retrieve', 'deliverables_baseline')
        if self.action in read_actions:
            return [IsAuthenticated()]
        if self.action == 'line_items' and self.request.method == 'GET':
            return [IsAuthenticated()]
        if self.action == 'line_item_detail' and self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageJobOrPM()]

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
            except NotFoundError as e:
                from rest_framework.exceptions import NotFound
                raise NotFound(str(e))
            serializer.instance = updated
        else:
            serializer.instance = ChangeOrderService.update_fields(
                serializer.instance, **serializer.validated_data)

    def destroy(self, request, *args, **kwargs):
        co = self.get_object()
        try:
            ChangeOrderService.discard_draft(co.pk)
        except NotFoundError as e:
            return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response({'message': 'Change order discarded.'})

    @action(detail=True, methods=['post'], url_path='line-items-from-service',
            url_name='line-items-from-service')
    def line_items_from_service(self, request, pk=None):
        """Create a deferred service line (service_item descriptor + snapshot).

        Mints NO Task; the Task crystallizes at CO acceptance
        (ChangeOrderAcceptanceService.on_accept). Mirrors the estimate's
        line-items-from-service action."""
        co = self.get_object()
        try:
            line_item = ChangeOrderService.add_line_item_from_service(
                co.pk,
                request.data.get('service_item'),
                request.data.get('qty'),
            )
        except NotFoundError as e:
            return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
        serializer = ChangeOrderLineItemSerializer(line_item)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='seed-new', url_name='seed-new')
    def seed_new(self, request, pk=None):
        """Create a new draft CO by copying all line items from an existing CO."""
        try:
            new_co = ChangeOrderService.seed_new(pk)
        except NotFoundError as e:
            return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(new_co)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='send-defaults')
    def send_defaults(self, request, pk=None):
        """Pre-populated values for the Send-to-customer form (link, no PDF)."""
        from apps.estimates.services import ChangeOrderEmailService
        co = self.get_object()
        return Response(ChangeOrderEmailService.get_email_defaults(co))

    @action(detail=True, methods=['post'], url_path='send')
    def send(self, request, pk=None):
        """Send the change order to the customer (portal link, no attachment).
        Transitions draft -> open on success. Body: to, subject, body, cc, bcc
        (cc/bcc comma-separated). Multipart attachments via request.FILES."""
        from apps.estimates.services import ChangeOrderEmailService
        co = self.get_object()
        to = request.data.get('to', '').strip()
        if not to:
            return Response(
                {'to': ['Recipient email address is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        subject = request.data.get('subject', '')
        body = request.data.get('body', '')
        cc = [c.strip() for c in request.data.get('cc', '').split(',') if c.strip()]
        bcc = [b.strip() for b in request.data.get('bcc', '').split(',') if b.strip()]
        extra_attachments = []
        for uploaded in request.FILES.getlist('attachments'):
            extra_attachments.append((
                uploaded.name, uploaded.read(),
                uploaded.content_type or 'application/octet-stream',
            ))
        try:
            record = ChangeOrderEmailService.send_change_order(
                co, to=to, subject=subject, body=body, cc=cc, bcc=bcc,
                extra_attachments=extra_attachments,
            )
        except DjangoValidationError:
            raise  # plain validation errors render via the contract handler
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({
            'email_record_id': record.email_record_id,
            'change_order_status': co.status,
        })

    @action(
        detail=True,
        methods=['get'],
        url_path='deliverables-baseline',
        url_name='deliverables-baseline',
        permission_classes=[IsAuthenticated],
    )
    def deliverables_baseline(self, request, pk=None):
        """Return the DeliverableSnapshot rows for the document this CO amends.

        The baseline is the latest accepted ChangeOrder on the same estimate
        created before this CO (if one exists), otherwise the accepted Estimate.
        These are the prior agreed deliverable scope that this CO's live
        deliverables should be diffed against.
        """
        co = self.get_object()
        from apps.deliverables.models import DeliverableSnapshot
        from apps.api.deliverables.serializers import DeliverableSnapshotSerializer

        baseline_doc = ChangeOrderService.baseline_document(co=co)
        if isinstance(baseline_doc, ChangeOrder):
            snapshots = DeliverableSnapshot.objects.filter(
                change_order=baseline_doc,
            ).order_by('sort_order')
        else:
            snapshots = DeliverableSnapshot.objects.filter(
                estimate=baseline_doc,
            ).order_by('sort_order')

        serializer = DeliverableSnapshotSerializer(snapshots, many=True)
        return Response({'baseline': serializer.data})
