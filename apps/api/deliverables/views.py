from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.api.permissions import CanManageJobs
from apps.deliverables.models import Deliverable, Shipment, ShipmentItem
from apps.deliverables.services import DeliverableService, ShipmentService
from apps.core.services import NotFoundError
from .serializers import (
    DeliverableSerializer, ShipmentSerializer, ShipmentItemSerializer,
)


def _validation_error_response(exc):
    detail = exc.message_dict if hasattr(exc, 'message_dict') else (
        exc.messages if hasattr(exc, 'messages') else [str(exc)]
    )
    return Response({'detail': detail}, status=status.HTTP_400_BAD_REQUEST)


class JobDeliverablesView(APIView):
    """GET + POST /api/jobs/<id>/deliverables/"""

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), CanManageJobs()]
        return [IsAuthenticated()]

    def get(self, request, job_id):
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_id)
        except Job.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        qs = Deliverable.objects.filter(job=job).order_by('sort_order')
        serializer = DeliverableSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request, job_id):
        data = request.data or {}
        try:
            d = DeliverableService.create(
                job_id=job_id,
                description=data.get('description', ''),
                qty_ordered=data.get('qty_ordered'),
                units=data.get('units', ''),
                sort_order=data.get('sort_order'),
            )
        except NotFoundError:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response(DeliverableSerializer(d).data, status=status.HTTP_201_CREATED)


class JobDeliverableDetailView(APIView):
    """GET / PATCH / DELETE /api/jobs/<id>/deliverables/<did>/"""

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageJobs()]

    def _get(self, job_id, deliverable_id):
        try:
            return Deliverable.objects.get(pk=deliverable_id, job_id=job_id)
        except Deliverable.DoesNotExist:
            return None

    def get(self, request, job_id, deliverable_id):
        d = self._get(job_id, deliverable_id)
        if d is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(DeliverableSerializer(d).data)

    def patch(self, request, job_id, deliverable_id):
        d = self._get(job_id, deliverable_id)
        if d is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            d = DeliverableService.update(deliverable=d, **(request.data or {}))
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response(DeliverableSerializer(d).data)

    def delete(self, request, job_id, deliverable_id):
        d = self._get(job_id, deliverable_id)
        if d is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            DeliverableService.delete(deliverable=d)
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response({'message': 'Deliverable deleted.'})


class JobDeliverablesReorderView(APIView):
    permission_classes = [IsAuthenticated, CanManageJobs]

    def post(self, request, job_id):
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_id)
        except Job.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        ordered_ids = (request.data or {}).get('ordered_ids', [])
        if not isinstance(ordered_ids, list) or not ordered_ids:
            return Response(
                {'ordered_ids': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            result = DeliverableService.reorder(job=job, ordered_ids=ordered_ids)
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response(DeliverableSerializer(result, many=True).data)


class JobDeliverablesEditabilityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, job_id):
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_id)
        except Job.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            'editable': DeliverableService.is_editable(job),
            'reason': DeliverableService.editability_reason(job),
        })


# --- Shipments ---


class JobShipmentsCreateView(APIView):
    """POST /api/jobs/<id>/shipments/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, job_id):
        try:
            shipment = ShipmentService.create(job_id=job_id)
        except NotFoundError:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response(ShipmentSerializer(shipment).data, status=status.HTTP_201_CREATED)


class ShipmentsListView(APIView):
    """GET /api/shipments/?job=<id>"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Shipment.objects.all().select_related('job').prefetch_related('items')
        job_id = request.query_params.get('job')
        if job_id:
            qs = qs.filter(job_id=job_id)
        serializer = ShipmentSerializer(qs, many=True)
        return Response({'results': serializer.data})


class ShipmentDetailView(APIView):
    """GET / PATCH / DELETE /api/shipments/<id>/"""

    permission_classes = [IsAuthenticated]

    def _get(self, shipment_id):
        try:
            return Shipment.objects.get(pk=shipment_id)
        except Shipment.DoesNotExist:
            return None

    def get(self, request, shipment_id):
        s = self._get(shipment_id)
        if s is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(ShipmentSerializer(s).data)

    def patch(self, request, shipment_id):
        s = self._get(shipment_id)
        if s is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            s = ShipmentService.update(shipment=s, **(request.data or {}))
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response(ShipmentSerializer(s).data)

    def delete(self, request, shipment_id):
        s = self._get(shipment_id)
        if s is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            ShipmentService.delete(shipment=s)
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response({'message': 'Shipment deleted.'})


class ShipmentPickUpView(APIView):
    """POST /api/shipments/<id>/pick-up/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, shipment_id):
        try:
            s = ShipmentService.mark_picked_up(shipment_id)
        except NotFoundError:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response(ShipmentSerializer(s).data)


class ShipmentItemsView(APIView):
    """GET + POST /api/shipments/<id>/items/"""

    permission_classes = [IsAuthenticated]

    def _get_shipment(self, shipment_id):
        try:
            return Shipment.objects.get(pk=shipment_id)
        except Shipment.DoesNotExist:
            return None

    def get(self, request, shipment_id):
        s = self._get_shipment(shipment_id)
        if s is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        qs = s.items.all().select_related('deliverable').order_by('deliverable__sort_order')
        return Response(ShipmentItemSerializer(qs, many=True).data)

    def post(self, request, shipment_id):
        s = self._get_shipment(shipment_id)
        if s is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        data = request.data or {}
        try:
            item = ShipmentService.add_item(
                shipment=s,
                deliverable_id=data.get('deliverable'),
                qty=data.get('qty'),
            )
        except NotFoundError:
            return Response({'detail': 'Deliverable not found.'}, status=status.HTTP_400_BAD_REQUEST)
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response(ShipmentItemSerializer(item).data, status=status.HTTP_201_CREATED)


class ShipmentItemDetailView(APIView):
    """PATCH + DELETE /api/shipments/<id>/items/<iid>/"""

    permission_classes = [IsAuthenticated]

    def _get(self, shipment_id, item_id):
        try:
            return ShipmentItem.objects.get(pk=item_id, shipment_id=shipment_id)
        except ShipmentItem.DoesNotExist:
            return None

    def patch(self, request, shipment_id, item_id):
        item = self._get(shipment_id, item_id)
        if item is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            item = ShipmentService.update_item(item=item, qty=(request.data or {}).get('qty'))
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response(ShipmentItemSerializer(item).data)

    def delete(self, request, shipment_id, item_id):
        item = self._get(shipment_id, item_id)
        if item is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            ShipmentService.remove_item(item=item)
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response({'message': 'Item deleted.'})


class ShipmentPackingListView(APIView):
    """GET /api/shipments/<id>/packing-list/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, shipment_id):
        try:
            s = Shipment.objects.select_related('job').get(pk=shipment_id)
        except Shipment.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        payload = ShipmentService.packing_list_payload(s)
        return Response(payload)
