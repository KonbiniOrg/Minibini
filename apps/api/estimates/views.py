from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateService
from apps.api.mixins import StatusTransitionMixin, LineItemMixin
from apps.api.permissions import CanManageJobs
from .serializers import EstimateSerializer, EstimateLineItemSerializer


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
        'revise': {'service': EstimateService.revise_estimate},
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

    @action(detail=True, methods=['get'], url_path='source-pool')
    def source_pool(self, request, pk=None):
        """Return the source pool for the wizard, drawn from this estimate's worksheet."""
        from apps.estimates.services import EstimateWizardService
        estimate = self.get_object()
        worksheet = estimate.worksheets.first()
        if not worksheet:
            return Response({'atoms': []})
        pool = EstimateWizardService.get_source_pool(worksheet)
        return Response(_serialize_pool(pool))

    @action(detail=True, methods=['post'], url_path='line-items-from-atoms')
    def line_items_from_atoms(self, request, pk=None):
        """Create a new estimate line item from a list of atoms."""
        from django.core.exceptions import ValidationError
        from apps.estimates.services import EstimateWizardService, EstimateClaimConflict

        estimate = self.get_object()
        atoms = request.data.get('atoms', [])
        try:
            line_item = EstimateWizardService.add_atoms_to_new_line_item(estimate, atoms)
        except EstimateClaimConflict as e:
            return Response(
                {'error': 'atoms_already_claimed', 'atom_ids': e.atom_ids},
                status=409,
            )
        except ValidationError as e:
            return Response({'error': str(e)}, status=400)
        serializer = EstimateLineItemSerializer(line_item)
        return Response(serializer.data, status=201)

    @action(
        detail=True, methods=['post'],
        url_path=r'line-items/(?P<line_item_pk>[^/.]+)/add-atoms',
    )
    def add_atoms(self, request, pk=None, line_item_pk=None):
        """Append atoms to an existing line item."""
        from django.core.exceptions import ValidationError
        from apps.estimates.models import EstimateLineItem
        from apps.estimates.services import EstimateWizardService, EstimateClaimConflict

        estimate = self.get_object()
        try:
            line_item = EstimateLineItem.objects.get(pk=line_item_pk, estimate=estimate)
        except EstimateLineItem.DoesNotExist:
            return Response({'error': 'Line item not found'}, status=404)

        atoms = request.data.get('atoms', [])
        try:
            EstimateWizardService.add_atoms_to_line_item(line_item, atoms)
        except EstimateClaimConflict as e:
            return Response(
                {'error': 'atoms_already_claimed', 'atom_ids': e.atom_ids},
                status=409,
            )
        except ValidationError as e:
            return Response({'error': str(e)}, status=400)

        line_item.refresh_from_db()
        serializer = EstimateLineItemSerializer(line_item)
        return Response(serializer.data, status=200)

    @action(
        detail=True, methods=['post'],
        url_path=r'line-items/(?P<line_item_pk>[^/.]+)/remove-atoms',
    )
    def remove_atoms(self, request, pk=None, line_item_pk=None):
        """Remove atoms from an existing line item."""
        from django.core.exceptions import ValidationError
        from apps.estimates.models import EstimateLineItem
        from apps.estimates.services import EstimateWizardService

        estimate = self.get_object()
        try:
            line_item = EstimateLineItem.objects.get(pk=line_item_pk, estimate=estimate)
        except EstimateLineItem.DoesNotExist:
            return Response({'error': 'Line item not found'}, status=404)

        source_ids = request.data.get('source_ids', [])
        try:
            result = EstimateWizardService.remove_atoms_from_line_item(line_item, source_ids)
        except ValidationError as e:
            return Response({'error': str(e)}, status=400)

        if result['line_item_deleted']:
            return Response({'line_item_deleted': True, 'line_item': None})

        line_item.refresh_from_db()
        return Response({
            'line_item_deleted': False,
            'line_item': EstimateLineItemSerializer(line_item).data,
        })


def _serialize_pool(pool):
    """Convert Decimals in the pool to strings for JSON serialization."""
    from decimal import Decimal

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
