import re
from django.core.exceptions import ValidationError
from django.db.models import Q, Value
from django.db.models.deletion import ProtectedError
from django.db.models.functions import Replace
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.contacts.models import Contact, Business, PaymentTerms, Tag
from apps.contacts.services import ContactService
from apps.core.models import CrmHistory
from apps.core.history import record_history
from apps.core.services import ServiceError, NotFoundError
from apps.api.mixins import ConfirmDeleteMixin
from apps.api.permissions import CanManageJobs
from apps.api.history.serializers import HistoryEntrySerializer
from .serializers import ContactSerializer, ContactDetailSerializer, BusinessSerializer, BusinessDetailSerializer, PaymentTermsSerializer, TagSerializer


class ContactViewSet(ConfirmDeleteMixin, viewsets.ModelViewSet):
    queryset = Contact.objects.all().order_by('last_name', 'first_name')
    serializer_class = ContactSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'history', 'notes', 'financials'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageJobs()]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ContactDetailSerializer
        return ContactSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        business = self.request.query_params.get('business')
        if business:
            qs = qs.filter(business_id=business)
        starts_with = self.request.query_params.get('starts_with')
        if starts_with == '0-9':
            qs = qs.filter(first_name__regex=r'^[0-9]')
        elif starts_with:
            qs = qs.filter(first_name__istartswith=starts_with)
        tag_ids = self.request.query_params.getlist('tag')
        for tag_id in tag_ids:
            qs = qs.filter(tags__tag_id=tag_id)

        search = self.request.query_params.get('search', '').strip()
        if search:
            phone_search = re.sub(r'[\s\-.()+]', '', search)

            def strip_phone(field):
                return Replace(Replace(Replace(Replace(Replace(
                    field,
                    Value(' '), Value('')),
                    Value('-'), Value('')),
                    Value('.'), Value('')),
                    Value('('), Value('')),
                    Value(')'), Value(''))

            qs = qs.annotate(
                mobile_clean=strip_phone('mobile_number'),
                work_clean=strip_phone('work_number'),
                home_clean=strip_phone('home_number'),
            )
            q = (
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search) |
                Q(business__business_name__icontains=search)
            )
            if phone_search:
                q |= (
                    Q(mobile_clean__icontains=phone_search) |
                    Q(work_clean__icontains=phone_search) |
                    Q(home_clean__icontains=phone_search)
                )
            qs = qs.filter(q)
        return qs

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

    def get_deletion_impact(self, contact):
        from apps.jobs.models import Job
        return {'jobs': Job.objects.filter(contact=contact).count()}

    def perform_confirmed_destroy(self, contact):
        try:
            ContactService.delete_contact(contact.pk)
        except ProtectedError:
            return Response(
                {'detail': 'Cannot delete this contact — it is still referenced by other records.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (ServiceError, ValidationError) as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'message': f'"{contact}" has been deleted.',
        })

    @action(detail=True, methods=['get'], url_path='history', url_name='history')
    def history(self, request, pk=None):
        contact = self.get_object()
        entries = CrmHistory.objects.filter(
            object_type='contact', object_id=contact.pk
        ).select_related('user')
        page = self.paginate_queryset(entries)
        if page is not None:
            serializer = HistoryEntrySerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = HistoryEntrySerializer(entries, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='notes', url_name='notes')
    def notes(self, request, pk=None):
        obj = self.get_object()
        text = request.data.get('text', '').strip()
        if not text:
            return Response(
                {'text': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        entry = record_history(
            entry_type='note',
            object_type='contact',
            object_id=obj.pk,
            user=request.user,
            text=text,
        )
        serializer = HistoryEntrySerializer(entry)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='financials', url_name='financials')
    def financials(self, request, pk=None):
        from decimal import Decimal
        from apps.jobs.financials import compute_job_financials
        contact = self.get_object()
        total_invoiced = Decimal('0')
        total_profit = Decimal('0')
        for job in contact.job_set.all():
            fin = compute_job_financials(job)
            total_invoiced += fin['invoiced']
            total_profit += fin['profit']
        return Response({
            'invoiced': str(total_invoiced.quantize(Decimal('0.01'))),
            'profit': str(total_profit.quantize(Decimal('0.01'))),
        })

    @action(detail=True, methods=['post'], url_path='add-tag')
    def add_tag(self, request, pk=None):
        contact = self.get_object()
        name = request.data.get('name', '').strip()
        if not name:
            return Response({'detail': 'Tag name is required.'}, status=status.HTTP_400_BAD_REQUEST)
        tag, _ = Tag.objects.get_or_create(name=name)
        contact.tags.add(tag)
        return Response(TagSerializer(contact.tags.all(), many=True).data)

    @action(detail=True, methods=['post'], url_path='remove-tag')
    def remove_tag(self, request, pk=None):
        contact = self.get_object()
        tag_id = request.data.get('tag_id')
        if not tag_id:
            return Response({'detail': 'tag_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        contact.tags.remove(tag_id)
        return Response(TagSerializer(contact.tags.all(), many=True).data)


class BusinessViewSet(ConfirmDeleteMixin, viewsets.ModelViewSet):
    queryset = Business.objects.all().order_by('business_name')
    serializer_class = BusinessSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'history', 'notes', 'financials'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageJobs()]

    def get_queryset(self):
        qs = super().get_queryset()
        starts_with = self.request.query_params.get('starts_with')
        if starts_with == '0-9':
            qs = qs.filter(business_name__regex=r'^[0-9]')
        elif starts_with:
            qs = qs.filter(business_name__istartswith=starts_with)
        tag_ids = self.request.query_params.getlist('tag')
        for tag_id in tag_ids:
            qs = qs.filter(tags__tag_id=tag_id)

        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(business_name__icontains=search) |
                Q(our_reference_code__icontains=search) |
                Q(business_phone__icontains=search) |
                Q(business_address__icontains=search)
            )
        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return BusinessDetailSerializer
        return BusinessSerializer

    def perform_create(self, serializer):
        data = serializer.validated_data
        default_contact = data.pop('default_contact', None)
        if default_contact:
            contact_pk = default_contact.pk if hasattr(default_contact, 'pk') else default_contact
            business = ContactService.create_business_for_contact(contact_pk, **data)
        else:
            raise ServiceError('default_contact_id is required when creating a business')
        serializer.instance = business

    def perform_update(self, serializer):
        ContactService.update_business(self.get_object().pk, **serializer.validated_data)

    def get_deletion_impact(self, business):
        from apps.jobs.models import Job
        from apps.purchasing.models import PurchaseOrder, Bill
        return {
            'jobs': Job.objects.filter(contact__business=business).count(),
            'purchase_orders': PurchaseOrder.objects.filter(business=business).count(),
            'bills': Bill.objects.filter(business=business).count(),
            'contacts': Contact.objects.filter(business=business).count(),
        }

    def perform_confirmed_destroy(self, business):
        contact_count = Contact.objects.filter(business=business).count()
        business_name = business.business_name

        try:
            ContactService.delete_business(business.pk)
        except ProtectedError:
            return Response(
                {'detail': 'Cannot delete this business — it is still referenced by purchase orders or bills.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (ServiceError, ValidationError) as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)

        msg = f'"{business_name}" has been deleted.'
        if contact_count:
            msg += f' {contact_count} contact(s) were disassociated.'
        return Response({'message': msg})

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
        except (ServiceError, NotFoundError, ValidationError) as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)
        business = self.get_object()
        return Response(BusinessSerializer(business).data)

    @action(detail=True, methods=['get'], url_path='history', url_name='history')
    def history(self, request, pk=None):
        business = self.get_object()
        contact_ids = list(Contact.objects.filter(business=business).values_list('pk', flat=True))
        q = Q(object_type='business', object_id=business.pk)
        if contact_ids:
            q |= Q(object_type='contact', object_id__in=contact_ids)
        entries = CrmHistory.objects.filter(q).select_related('user')
        page = self.paginate_queryset(entries)
        if page is not None:
            serializer = HistoryEntrySerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = HistoryEntrySerializer(entries, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='notes', url_name='notes')
    def notes(self, request, pk=None):
        obj = self.get_object()
        text = request.data.get('text', '').strip()
        if not text:
            return Response(
                {'text': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        entry = record_history(
            entry_type='note',
            object_type='business',
            object_id=obj.pk,
            user=request.user,
            text=text,
        )
        serializer = HistoryEntrySerializer(entry)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='financials', url_name='financials')
    def financials(self, request, pk=None):
        from decimal import Decimal
        from apps.jobs.financials import compute_job_financials
        from apps.jobs.models import Job
        business = self.get_object()
        total_invoiced = Decimal('0')
        total_profit = Decimal('0')
        for job in Job.objects.filter(contact__business=business):
            fin = compute_job_financials(job)
            total_invoiced += fin['invoiced']
            total_profit += fin['profit']
        return Response({
            'invoiced': str(total_invoiced.quantize(Decimal('0.01'))),
            'profit': str(total_profit.quantize(Decimal('0.01'))),
        })

    @action(detail=True, methods=['post'], url_path='add-tag')
    def add_tag(self, request, pk=None):
        business = self.get_object()
        name = request.data.get('name', '').strip()
        if not name:
            return Response({'detail': 'Tag name is required.'}, status=status.HTTP_400_BAD_REQUEST)
        tag, _ = Tag.objects.get_or_create(name=name)
        business.tags.add(tag)
        return Response(TagSerializer(business.tags.all(), many=True).data)

    @action(detail=True, methods=['post'], url_path='remove-tag')
    def remove_tag(self, request, pk=None):
        business = self.get_object()
        tag_id = request.data.get('tag_id')
        if not tag_id:
            return Response({'detail': 'tag_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        business.tags.remove(tag_id)
        return Response(TagSerializer(business.tags.all(), many=True).data)


class TagViewSet(viewsets.ModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer

    def get_permissions(self):
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(name__icontains=search)
        return qs


class PaymentTermsViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PaymentTerms.objects.all()
    serializer_class = PaymentTermsSerializer
    pagination_class = None
