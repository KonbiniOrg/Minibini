from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.contacts.models import Contact, Business, PaymentTerms
from apps.contacts.services import ContactService
from apps.core.services import ServiceError, NotFoundError
from .serializers import ContactSerializer, BusinessSerializer, PaymentTermsSerializer


class ContactViewSet(viewsets.ModelViewSet):
    queryset = Contact.objects.all().order_by('last_name', 'first_name')
    serializer_class = ContactSerializer
    lookup_field = 'pk'

    def perform_create(self, serializer):
        data = serializer.validated_data
        business = data.pop('business', None)
        business_pk = None
        if business:
            business_pk = business.pk if hasattr(business, 'pk') else business
        contact = ContactService.create_contact(business_pk=business_pk, **data)
        serializer.instance = contact

    def perform_update(self, serializer):
        data = serializer.validated_data
        business = data.pop('business', None)
        kwargs = dict(data)
        if business is not None:
            kwargs['business_pk'] = business.pk if hasattr(business, 'pk') else business
        ContactService.update_contact(self.get_object().pk, **kwargs)
        serializer.instance = Contact.objects.get(pk=self.get_object().pk)

    def destroy(self, request, *args, **kwargs):
        contact = self.get_object()
        confirm = request.query_params.get('confirm', '').lower() == 'true'

        if not confirm:
            from apps.jobs.models import Job
            impact = {
                'jobs': Job.objects.filter(contact=contact).count(),
            }
            return Response({
                'confirm_required': True,
                'impact': impact,
            })

        try:
            ContactService.delete_contact(contact.pk)
        except ServiceError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BusinessViewSet(viewsets.ModelViewSet):
    queryset = Business.objects.all().order_by('business_name')
    serializer_class = BusinessSerializer
    lookup_field = 'pk'

    def perform_create(self, serializer):
        data = serializer.validated_data
        default_contact = data.pop('default_contact', None)
        if default_contact and hasattr(default_contact, 'pk'):
            default_contact = default_contact.pk
        contacts_data = []
        if default_contact:
            contacts_data = [{'contact_pk': default_contact}]
        business = ContactService.create_business(contacts_data=contacts_data, **data)
        serializer.instance = business

    def perform_update(self, serializer):
        ContactService.update_business(self.get_object().pk, **serializer.validated_data)

    def destroy(self, request, *args, **kwargs):
        business = self.get_object()
        confirm = request.query_params.get('confirm', '').lower() == 'true'

        if not confirm:
            from apps.jobs.models import Job
            from apps.purchasing.models import PurchaseOrder, Bill
            impact = {
                'jobs': Job.objects.filter(contact__business=business).count(),
                'purchase_orders': PurchaseOrder.objects.filter(business=business).count(),
                'bills': Bill.objects.filter(business=business).count(),
                'contacts': Contact.objects.filter(business=business).count(),
            }
            return Response({
                'confirm_required': True,
                'impact': impact,
            })

        try:
            ContactService.delete_business(business.pk)
        except ServiceError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='set-default-contact')
    def set_default_contact(self, request, pk=None):
        contact_id = request.data.get('contact_id')
        if not contact_id:
            return Response(
                {'contact_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            ContactService.set_default_contact(pk, contact_id)
        except (ServiceError, NotFoundError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        business = self.get_object()
        return Response(BusinessSerializer(business).data)


class PaymentTermsViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PaymentTerms.objects.all()
    serializer_class = PaymentTermsSerializer
    pagination_class = None
