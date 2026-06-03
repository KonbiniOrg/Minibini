from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.api.mixins import LineItemMixin, StatusTransitionMixin
from apps.api.permissions import CanManageJobs
from apps.core.services import NotFoundError, ServiceError
from apps.estimates.models import Estimate, EstimateLineItem, EstWorksheet
from apps.estimates.services import (
    EstimateClaimConflict,
    EstimateService,
    EstimateWizardService,
)

from .serializers import EstimateLineItemSerializer, EstimateSerializer


class EstimateViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = Estimate.objects.all().order_by('-created_date')
    serializer_class = EstimateSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        read_actions = ('list', 'retrieve')
        mixed_actions = ('line_items',)
        if self.action in read_actions:
            return [IsAuthenticated()]
        if self.action in mixed_actions and self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageJobs()]

    # Line item mixin config
    line_item_serializer_class = EstimateLineItemSerializer
    line_item_parent_field = 'estimate'
    line_item_service_class = EstimateService

    # Status actions
    status_actions = {
        'mark-open': {'service': EstimateService.mark_open},
    }

    def get_queryset(self):
        qs = super().get_queryset()
        job = self.request.query_params.get('job')
        if job:
            qs = qs.filter(job_id=job)
        return qs

    def perform_create(self, serializer):
        data = serializer.validated_data
        job = data.get('job')
        job_pk = job.pk if hasattr(job, 'pk') else job
        estimate = EstimateService.create_for_job(job_pk)
        serializer.instance = estimate

    def perform_update(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        estimate = self.get_object()
        try:
            EstimateService.discard_draft(estimate)
        except DjangoValidationError as e:
            msg = e.messages[0] if hasattr(e, 'messages') else str(e)
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'message': 'Estimate discarded'})

    @action(detail=True, methods=['post'], url_path='revise')
    def revise(self, request, pk=None):
        try:
            new_estimate = EstimateService.revise_estimate(pk)
        except NotFoundError:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        except (ServiceError, DjangoValidationError) as e:
            msg = e.messages[0] if hasattr(e, 'messages') else str(e)
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.get_serializer(new_estimate)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='source-pool')
    def source_pool(self, request, pk=None):
        """Return the source pool for the wizard, drawn from the job's worksheet."""
        estimate = self.get_object()
        worksheet = (
            EstWorksheet.objects.filter(job_id=estimate.job_id)
            .order_by('-est_worksheet_id')
            .first()
        )
        if not worksheet:
            return Response({'atoms': []})
        pool = EstimateWizardService.get_source_pool(worksheet)
        return Response(_serialize_pool(pool))

    @action(detail=True, methods=['post'], url_path='line-items-from-atoms')
    def line_items_from_atoms(self, request, pk=None):
        """Create a new estimate line item from a list of atoms."""
        estimate = self.get_object()
        atoms = request.data.get('atoms', [])
        try:
            line_item = EstimateWizardService.add_atoms_to_new_line_item(estimate, atoms)
        except EstimateClaimConflict as e:
            return Response(
                {'error': 'atoms_already_claimed', 'atom_ids': e.atom_ids},
                status=status.HTTP_409_CONFLICT,
            )
        except DjangoValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        serializer = EstimateLineItemSerializer(line_item)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True, methods=['post'],
        url_path=r'line-items/(?P<line_item_pk>[^/.]+)/add-atoms',
    )
    def add_atoms(self, request, pk=None, line_item_pk=None):
        """Append atoms to an existing line item."""
        estimate = self.get_object()
        try:
            line_item = EstimateLineItem.objects.get(pk=line_item_pk, estimate=estimate)
        except EstimateLineItem.DoesNotExist:
            return Response({'error': 'Line item not found'}, status=status.HTTP_404_NOT_FOUND)

        atoms = request.data.get('atoms', [])
        try:
            EstimateWizardService.add_atoms_to_line_item(line_item, atoms)
        except EstimateClaimConflict as e:
            return Response(
                {'error': 'atoms_already_claimed', 'atom_ids': e.atom_ids},
                status=status.HTTP_409_CONFLICT,
            )
        except DjangoValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        line_item.refresh_from_db()
        serializer = EstimateLineItemSerializer(line_item)
        return Response(serializer.data)

    @action(
        detail=True, methods=['post'],
        url_path=r'line-items/(?P<line_item_pk>[^/.]+)/remove-atoms',
    )
    def remove_atoms(self, request, pk=None, line_item_pk=None):
        """Remove atoms from an existing line item."""
        estimate = self.get_object()
        try:
            line_item = EstimateLineItem.objects.get(pk=line_item_pk, estimate=estimate)
        except EstimateLineItem.DoesNotExist:
            return Response({'error': 'Line item not found'}, status=status.HTTP_404_NOT_FOUND)

        source_ids = request.data.get('source_ids', [])
        try:
            result = EstimateWizardService.remove_atoms_from_line_item(line_item, source_ids)
        except DjangoValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        if result['line_item_deleted']:
            return Response({'line_item_deleted': True, 'line_item': None})

        line_item.refresh_from_db()
        return Response({
            'line_item_deleted': False,
            'line_item': EstimateLineItemSerializer(line_item).data,
        })

    @action(detail=True, methods=['get'], url_path='send-defaults')
    def send_defaults(self, request, pk=None):
        """Pre-populated values for the Send Email page."""
        from apps.estimates.services import EstimateEmailService
        estimate = self.get_object()
        return Response(EstimateEmailService.get_email_defaults(estimate))

    @action(detail=True, methods=['post'], url_path='send')
    def send(self, request, pk=None):
        """Send the estimate as a PDF attachment. Transitions draft -> open
        on success. Body: to, subject, body, cc, bcc (all strings; cc/bcc
        comma-separated). Multipart attachments come through request.FILES."""
        from apps.estimates.services import EstimateEmailService
        estimate = self.get_object()
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
            record = EstimateEmailService.send_estimate(
                estimate,
                to=to, subject=subject, body=body, cc=cc, bcc=bcc,
                extra_attachments=extra_attachments,
                user=request.user,
            )
        except DjangoValidationError as e:
            return Response(
                {'detail': e.messages if hasattr(e, 'messages') else str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            # SMTP / unexpected failure — the outbound EmailRecord has been
            # persisted with last_send_error set, but the request is failing.
            return Response(
                {'detail': str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({
            'email_record_id': record.email_record_id,
            'estimate_status': estimate.status,
        })


def _serialize_pool(pool):
    """Convert Decimals in the pool to strings for JSON serialization."""
    def _s(value):
        if isinstance(value, Decimal):
            return str(value)
        return value

    return {
        'atoms': [
            {k: _s(v) for k, v in atom.items()}
            for atom in pool['atoms']
        ],
    }
