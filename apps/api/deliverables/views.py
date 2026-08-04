from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.api.mixins import JSONDestroyMixin, StatusTransitionMixin, JobScopedPermissionMixin
from apps.api.permissions import CanManageFinancials, CanManageJobOrPM
from apps.core.services import NotFoundError
from apps.deliverables.models import Deliverable, Shipment, ShipmentItem
from apps.deliverables.services import DeliverableService, ShipmentService
from .serializers import (
    DeliverableSerializer, ShipmentSerializer, ShipmentItemSerializer,
)


class DeliverableViewSet(JobScopedPermissionMixin, JSONDestroyMixin, ModelViewSet):
    """Job-nested CRUD for Deliverable; all logic lives in DeliverableService."""

    serializer_class = DeliverableSerializer
    destroy_response_message = 'Deliverable deleted.'
    job_object_path = 'job'
    job_url_kwarg = 'job_id'

    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'editability'):
            return [IsAuthenticated()]
        if self.action == 'create_work_structure':
            # Money-shaped creation (spec §9 rule 7): this mints a Task row
            # — even though it's deliberately money-LESS (rate/AC NULL) —
            # so the gate matches flat-task creation
            # (docs/plans/2026-08-02-task-owned-money.md §6: can_manage_jobs,
            # the job's PM, or financials), not the plain CanManageJobOrPM
            # the rest of this viewset uses.
            return [IsAuthenticated(), (CanManageJobOrPM | CanManageFinancials)()]
        return [IsAuthenticated(), CanManageJobOrPM()]

    def get_queryset(self):
        return Deliverable.objects.filter(
            job_id=self.kwargs['job_id'],
        ).order_by('sort_order')

    def get_object(self):
        try:
            return self.get_queryset().get(pk=self.kwargs['deliverable_id'])
        except Deliverable.DoesNotExist:
            raise NotFound()

    def _get_job_or_404(self):
        from apps.jobs.models import Job
        try:
            return Job.objects.get(pk=self.kwargs['job_id'])
        except Job.DoesNotExist:
            raise NotFound()

    def list(self, request, *args, **kwargs):
        self._get_job_or_404()
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    def retrieve(self, request, *args, **kwargs):
        return Response(self.get_serializer(self.get_object()).data)

    def create(self, request, *args, **kwargs):
        data = request.data or {}
        try:
            deliverable = DeliverableService.create(
                job_id=self.kwargs['job_id'],
                description=data.get('description', ''),
                qty_ordered=data.get('qty_ordered'),
                units=data.get('units', ''),
                sort_order=data.get('sort_order'),
            )
        except NotFoundError:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            self.get_serializer(deliverable).data, status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        deliverable = self.get_object()
        deliverable = DeliverableService.update(
            deliverable=deliverable, **(request.data or {}),
        )
        return Response(self.get_serializer(deliverable).data)

    def destroy(self, request, *args, **kwargs):
        deliverable = self.get_object()
        DeliverableService.delete(deliverable=deliverable)
        return Response({'message': self.destroy_response_message})

    def reorder(self, request, *args, **kwargs):
        job = self._get_job_or_404()
        ordered_ids = (request.data or {}).get('ordered_ids', [])
        if not isinstance(ordered_ids, list) or not ordered_ids:
            return Response(
                {'ordered_ids': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = DeliverableService.reorder(job=job, ordered_ids=ordered_ids)
        return Response(self.get_serializer(result, many=True).data)

    def editability(self, request, *args, **kwargs):
        job = self._get_job_or_404()
        return Response({
            'editable': DeliverableService.is_editable(job),
            'reason': DeliverableService.editability_reason(job),
        })

    def create_work_structure(self, request, *args, **kwargs):
        """Deliverable -> Task bridge (spec §9 rule 7, reverse direction of
        Task.add_as_deliverable): mints a top-level, SCHEME-LESS task — no
        money (rate/accounting_category NULL) — copying description ->
        name, qty_ordered -> est_qty, units -> unit_label, entered-qty.
        Bypasses TaskService.create_direct (which mandates a rate_scheme)
        the same way estimate-acceptance's flat-task crystallization does
        (apps/estimates/acceptance.py) — a money-less task has no preset to
        stamp from. Links Deliverable.source_task to the new task
        (provenance only). Rejected when the deliverable is already linked."""
        from apps.jobs.models import Task
        from apps.jobs.services import JobService, _assert_job_not_on_hold
        from apps.api.tasks.serializers import TaskSerializer
        deliverable = self.get_object()
        job = deliverable.job
        _assert_job_not_on_hold(job, 'create a work structure from this deliverable')
        if deliverable.source_task_id is not None:
            return Response(
                {'detail': 'This deliverable is already linked to a task.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        task = Task(
            job=job,
            name=(deliverable.description or 'Deliverable')[:100],
            qty_source=Task.QTY_ENTERED,
            est_qty=deliverable.qty_ordered,
            unit_label=deliverable.units,
            rate=None,
            accounting_category=None,
            source_scheme=None,
        )
        task.save()
        JobService.mark_work_reopened(job)
        deliverable.source_task = task
        deliverable.save(update_fields=['source_task', 'updated_at'])
        return Response(
            TaskSerializer(task, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )


class ShipmentViewSet(StatusTransitionMixin, JSONDestroyMixin, ModelViewSet):
    """Flat CRUD for Shipment + nested items; logic lives in ShipmentService.

    Pick-up is registered as a status transition via StatusTransitionMixin.
    """

    serializer_class = ShipmentSerializer
    permission_classes = [IsAuthenticated]
    destroy_response_message = 'Shipment deleted.'

    status_actions = {
        'pick-up': {'service': ShipmentService.mark_picked_up},
    }

    def get_queryset(self):
        return Shipment.objects.all().select_related('job').prefetch_related('items')

    def get_object(self):
        try:
            return self.get_queryset().get(pk=self.kwargs['pk'])
        except Shipment.DoesNotExist:
            raise NotFound()

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        job_id = request.query_params.get('job')
        if job_id:
            qs = qs.filter(job_id=job_id)
        return Response({'results': self.get_serializer(qs, many=True).data})

    def retrieve(self, request, *args, **kwargs):
        return Response(self.get_serializer(self.get_object()).data)

    def create_for_job(self, request, *args, **kwargs):
        try:
            shipment = ShipmentService.create(job_id=self.kwargs['job_id'])
        except NotFoundError:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            self.get_serializer(shipment).data, status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        shipment = self.get_object()
        shipment = ShipmentService.update(shipment=shipment, **(request.data or {}))
        return Response(self.get_serializer(shipment).data)

    def destroy(self, request, *args, **kwargs):
        shipment = self.get_object()
        ShipmentService.delete(shipment=shipment)
        return Response({'message': self.destroy_response_message})

    def items(self, request, *args, **kwargs):
        shipment = self.get_object()
        if request.method == 'GET':
            qs = shipment.items.all().select_related('deliverable').order_by(
                'deliverable__sort_order',
            )
            return Response(ShipmentItemSerializer(qs, many=True).data)
        data = request.data or {}
        try:
            item = ShipmentService.add_item(
                shipment=shipment,
                deliverable_id=data.get('deliverable'),
                qty=data.get('qty'),
            )
        except NotFoundError:
            return Response(
                {'detail': 'Deliverable not found.'}, status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            ShipmentItemSerializer(item).data, status=status.HTTP_201_CREATED,
        )

    def item_detail(self, request, *args, **kwargs):
        shipment = self.get_object()
        try:
            item = ShipmentItem.objects.get(
                pk=self.kwargs['item_id'], shipment=shipment,
            )
        except ShipmentItem.DoesNotExist:
            raise NotFound()
        if request.method == 'DELETE':
            ShipmentService.remove_item(item=item)
            return Response({'message': 'Item deleted.'})
        item = ShipmentService.update_item(
            item=item, qty=(request.data or {}).get('qty'),
        )
        return Response(ShipmentItemSerializer(item).data)

    def packing_list(self, request, *args, **kwargs):
        shipment = self.get_object()
        return Response(ShipmentService.packing_list_payload(shipment))
