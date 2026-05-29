from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.core.models import EmailRecord
from apps.core.services import EmailService, ServiceError, NotFoundError
from apps.core.email_utils import (
    parse_email_address,
    extract_company_from_signature,
    extract_email_body,
    trim_body_at_signoff,
    clean_subject_for_job_name,
    resolve_contact_links,
)
from apps.contacts.models import Contact, Business
from apps.api.permissions import CanManageJobs
from .serializers import EmailRecordSerializer


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def email_list(request):
    emails = EmailRecord.objects.select_related('temp_data').order_by('-created_at')
    job = request.query_params.get('job')
    if job:
        try:
            emails = emails.filter(job=int(job))
        except (TypeError, ValueError):
            return Response({'job': ['Must be an integer.']}, status=status.HTTP_400_BAD_REQUEST)
    from apps.api.pagination import StandardPagination
    paginator = StandardPagination()
    page = paginator.paginate_queryset(emails, request)
    serializer = EmailRecordSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def email_detail(request, pk):
    try:
        email = EmailRecord.objects.select_related('temp_data').get(pk=pk)
    except EmailRecord.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    data = EmailRecordSerializer(email).data
    try:
        service = EmailService()
        content = service.get_email_content(pk)
        data['content'] = content
    except Exception:
        data['content'] = None

    # Map known email addresses to Contact rows so the SPA can render
    # From/To/CC entries as links when we already know the person.
    addresses = []
    if data.get('content'):
        c = data['content']
        if c.get('from'):
            addresses.append(c['from'])
        addresses.extend(c.get('to') or [])
        addresses.extend(c.get('cc') or [])
    temp = getattr(email, 'temp_data', None)
    if temp:
        addresses.append(temp.from_email or '')
        addresses.extend(a.strip() for a in (temp.to_email or '').split(',') if a.strip())
        addresses.extend(a.strip() for a in (temp.cc_email or '').split(',') if a.strip())
    data['contact_links'] = resolve_contact_links(addresses)

    return Response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, CanManageJobs])
def link_to_job(request, pk):
    job_id = request.data.get('job_id')
    if not job_id:
        return Response(
            {'job_id': ['This field is required.']},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        job_id = int(job_id)
    except (TypeError, ValueError):
        return Response(
            {'job_id': ['Must be an integer.']},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        EmailService.associate_with_job(pk, job_id)
    except NotFoundError as e:
        return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
    except ServiceError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    email = EmailRecord.objects.get(pk=pk)
    return Response(EmailRecordSerializer(email).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, CanManageJobs])
def unlink_from_job(request, pk):
    try:
        EmailService.disassociate_from_job(pk)
    except NotFoundError as e:
        return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
    except ServiceError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    email = EmailRecord.objects.get(pk=pk)
    return Response(EmailRecordSerializer(email).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, CanManageJobs])
def create_job_from_email(request, pk):
    """Create a job from an email — delegates to JobService."""
    from django.core.exceptions import ValidationError as DjangoValidationError
    from apps.jobs.services import JobService
    try:
        EmailRecord.objects.select_related('temp_data').get(pk=pk)
    except EmailRecord.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    contact_id = request.data.get('contact')
    name = request.data.get('name', '')
    description = request.data.get('description', '')
    if not contact_id:
        return Response(
            {'contact': ['This field is required.']},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        job = JobService.create_job(
            name=name, description=description, contact_id=contact_id,
        )
    except DjangoValidationError as e:
        return Response(
            e.message_dict if hasattr(e, 'message_dict') else {'detail': e.messages},
            status=status.HTTP_400_BAD_REQUEST,
        )
    EmailService.associate_with_job(pk, job.pk)
    return Response({
        'job_id': job.pk,
        'job_number': job.job_number,
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated, CanManageJobs])
def sender_info(request, pk):
    """Parse an email's sender + body and suggest matching contacts/businesses."""
    try:
        email_record = EmailRecord.objects.select_related('temp_data').get(pk=pk)
    except EmailRecord.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    service = EmailService()
    content = service.get_email_content(pk)
    if not content:
        return Response(
            {'detail': 'Email content could not be retrieved from server.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    sender_name, sender_email = parse_email_address(content.get('from', ''))
    # Full body without the broad signature trim, then apply the precise
    # sign-off trim so the SPA can offer the trimmed body as the description.
    body = trim_body_at_signoff(extract_email_body(content, trim_signature=False))
    company = extract_company_from_signature(content.get('text', ''))
    temp = getattr(email_record, 'temp_data', None)
    raw_subject = (temp.subject if temp else '') or content.get('subject', '') or ''
    subject = clean_subject_for_job_name(raw_subject)

    matching_contacts = []
    if sender_email:
        for c in Contact.objects.filter(email=sender_email).select_related('business'):
            matching_contacts.append({
                'id': c.contact_id,
                'name': c.name,
                'email': c.email,
                'business': (
                    {'id': c.business.business_id, 'business_name': c.business.business_name}
                    if c.business else None
                ),
            })

    matching_businesses = []
    if company:
        for b in Business.objects.filter(business_name__iexact=company):
            matching_businesses.append({
                'id': b.business_id,
                'business_name': b.business_name,
            })

    return Response({
        'sender_name': sender_name,
        'sender_email': sender_email,
        'subject': subject,
        'suggested_body': body,
        'matching_contacts': matching_contacts,
        'extracted_company': company,
        'matching_businesses': matching_businesses,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def refresh(request):
    """Trigger an IMAP fetch for new emails. Returns fetch stats."""
    from django.conf import settings as django_settings
    service = EmailService()
    try:
        stats = service.fetch_emails_by_date_range(days_back=30)
    except Exception as e:
        stats = {'new': 0, 'existing': 0, 'errors': [str(e)]}
    return Response({
        'new': stats.get('new', 0),
        'existing': stats.get('existing', 0),
        'errors': stats.get('errors', []),
        'email_address': getattr(django_settings, 'EMAIL_HOST_USER', '') or '',
    })


def _stub_501(endpoint):
    @api_view(['POST'])
    @permission_classes([IsAuthenticated])
    def view(request, *args, **kwargs):
        return Response(
            {'detail': 'Not yet implemented.', 'endpoint': endpoint},
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )
    return view
