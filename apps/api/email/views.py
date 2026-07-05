from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.core.models import EmailRecord
from apps.core.services import EmailService, ServiceError, NotFoundError
from django.conf import settings as django_settings
from apps.core.services import OutboundEmailService
from apps.core.email_utils import (
    build_reply_subject,
    build_reply_body,
)
from apps.core.email_utils import (
    parse_email_address,
    extract_company_from_signature,
    extract_email_body,
    trim_body_at_signoff,
    clean_subject_for_job_name,
    resolve_contact_links,
)
from apps.contacts.models import Contact, Business
from apps.api.permissions import CanManageJobs, CanManageFinancials
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


def _link_email_to(request, pk, target_field, body_key):
    """Shared body for link-to-<target> endpoints. Validates the body, calls
    EmailService.associate_with, and returns the updated serializer payload."""
    target_pk = request.data.get(body_key)
    if not target_pk:
        return Response(
            {body_key: ['This field is required.']},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        target_pk = int(target_pk)
    except (TypeError, ValueError):
        return Response(
            {body_key: ['Must be an integer.']},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        EmailService.associate_with(pk, target_field, target_pk)
    except NotFoundError as e:
        return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
    except ServiceError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    email = EmailRecord.objects.get(pk=pk)
    return Response(EmailRecordSerializer(email).data)


def _unlink_email_from(pk, target_field):
    try:
        EmailService.disassociate_from(pk, target_field)
    except NotFoundError as e:
        return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
    except ServiceError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    email = EmailRecord.objects.get(pk=pk)
    return Response(EmailRecordSerializer(email).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, CanManageJobs])
def link_to_job(request, pk):
    return _link_email_to(request, pk, 'job', 'job_id')


@api_view(['POST'])
@permission_classes([IsAuthenticated, CanManageJobs])
def unlink_from_job(request, pk):
    return _unlink_email_from(pk, 'job')


@api_view(['POST'])
@permission_classes([IsAuthenticated, CanManageFinancials])
def link_to_po(request, pk):
    return _link_email_to(request, pk, 'purchase_order', 'po_id')


@api_view(['POST'])
@permission_classes([IsAuthenticated, CanManageFinancials])
def unlink_from_po(request, pk):
    return _unlink_email_from(pk, 'purchase_order')


@api_view(['POST'])
@permission_classes([IsAuthenticated, CanManageFinancials])
def link_to_bill(request, pk):
    return _link_email_to(request, pk, 'bill', 'bill_id')


@api_view(['POST'])
@permission_classes([IsAuthenticated, CanManageFinancials])
def unlink_from_bill(request, pk):
    return _unlink_email_from(pk, 'bill')


@api_view(['POST'])
@permission_classes([IsAuthenticated, CanManageFinancials])
def create_po_from_email(request, pk):
    """Create a Purchase Order from an email and link the email to it.

    Body: ``{vendor_business_id}``. Only the vendor (Business) is required;
    line items are added on the PO detail page after creation. Mirrors
    create_job_from_email.
    """
    from apps.purchasing.services import PurchaseOrderService
    from apps.contacts.models import Business
    try:
        EmailRecord.objects.get(pk=pk)
    except EmailRecord.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    vendor_id = request.data.get('vendor_business_id')
    if not vendor_id:
        return Response(
            {'vendor_business_id': ['This field is required.']},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        vendor_id = int(vendor_id)
    except (TypeError, ValueError):
        return Response(
            {'vendor_business_id': ['Must be an integer.']},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        business = Business.objects.get(pk=vendor_id)
    except Business.DoesNotExist:
        return Response(
            {'vendor_business_id': [f'Business {vendor_id} not found.']},
            status=status.HTTP_404_NOT_FOUND,
        )
    po = PurchaseOrderService.create_po(business=business)
    EmailService.associate_with(pk, 'purchase_order', po.pk)
    return Response(
        {'po_id': po.pk, 'po_number': po.po_number},
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated, CanManageJobs])
def create_job_from_email(request, pk):
    """Create a job from an email — delegates to JobService."""
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

    job = JobService.create_job(
        name=name, description=description, contact_id=contact_id,
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


def _compute_reply_all_cc(parent_temp):
    """Original to + cc, minus our own EMAIL_HOST_USER, de-duplicated,
    in original order (to-first then cc). Comma-separated string."""
    our_address = (getattr(django_settings, 'EMAIL_HOST_USER', '') or '').strip().lower()
    seen = set()
    if our_address:
        seen.add(our_address)
    out = []

    def add_addresses(raw):
        for piece in (raw or '').split(','):
            addr = piece.strip()
            if not addr:
                continue
            key = addr.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(addr)

    add_addresses(parent_temp.to_email)
    add_addresses(parent_temp.cc_email)
    return ', '.join(out)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def reply_defaults(request, pk):
    """Pre-populated form payload for a Reply or Reply All to email <pk>.

    Returns to/cc/bcc/reply_all_cc/subject/body, threading headers
    (in_reply_to, references) the SPA echoes back on submit, and the
    parent's association FKs the reply should inherit on send.
    """
    try:
        parent = EmailRecord.objects.select_related('temp_data').get(pk=pk)
    except EmailRecord.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    temp = getattr(parent, 'temp_data', None)

    to = ''
    reply_all_cc = ''
    subject_source = ''
    if temp:
        # 'From' may be 'Name <email>' — parse out just the email.
        _, sender_email = parse_email_address(temp.from_email or '')
        to = sender_email or temp.from_email or ''
        reply_all_cc = _compute_reply_all_cc(temp)
        subject_source = temp.subject or ''

    subject = build_reply_subject(subject_source)
    body = build_reply_body(parent)

    references_chain = (temp.references if temp else '') or ''
    # Append the parent's message_id to the References chain.
    if parent.message_id:
        if references_chain:
            references_chain = f'{references_chain} {parent.message_id}'
        else:
            references_chain = parent.message_id

    return Response({
        'to': to,
        'cc': '',
        'bcc': '',
        'reply_all_cc': reply_all_cc,
        'subject': subject,
        'body': body,
        'in_reply_to': parent.message_id or '',
        'references': references_chain,
        'inherit_associations': {
            'job': parent.job_id,
            'purchase_order': parent.purchase_order_id,
            'bill': parent.bill_id,
        },
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reply(request, pk):
    """Send a reply to email <pk>. Multipart body fields:

    - to, cc, bcc, subject, body (text)
    - in_reply_to, references (text — the SPA echoes them from
      /reply-defaults/)
    - inherit_job, inherit_purchase_order, inherit_bill — PK strings,
      any combination. The first non-blank in priority order
      Job > PO > Bill becomes the outbound's associate_with target.
    - attachments — zero or more uploaded files

    Returns {email_record_id} on success; 400 on missing to; 502 on
    SMTP failure with the outbound row's last_send_error populated.
    """
    try:
        EmailRecord.objects.get(pk=pk)
    except EmailRecord.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    to = (request.data.get('to') or '').strip()
    if not to:
        return Response(
            {'to': ['Recipient email address is required.']},
            status=status.HTTP_400_BAD_REQUEST,
        )
    subject = request.data.get('subject') or ''
    body = request.data.get('body') or ''
    cc = [c.strip() for c in (request.data.get('cc') or '').split(',') if c.strip()]
    bcc = [b.strip() for b in (request.data.get('bcc') or '').split(',') if b.strip()]
    in_reply_to = (request.data.get('in_reply_to') or '').strip()
    references = (request.data.get('references') or '').strip()

    associate_with = None
    inherit_job = (request.data.get('inherit_job') or '').strip()
    inherit_po = (request.data.get('inherit_purchase_order') or '').strip()
    inherit_bill = (request.data.get('inherit_bill') or '').strip()
    if inherit_job:
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=int(inherit_job))
        except (Job.DoesNotExist, ValueError):
            return Response({'inherit_job': ['Not found.']}, status=status.HTTP_400_BAD_REQUEST)
        associate_with = {'job': job}
    elif inherit_po:
        from apps.purchasing.models import PurchaseOrder
        try:
            po = PurchaseOrder.objects.get(pk=int(inherit_po))
        except (PurchaseOrder.DoesNotExist, ValueError):
            return Response({'inherit_purchase_order': ['Not found.']}, status=status.HTTP_400_BAD_REQUEST)
        associate_with = {'purchase_order': po}
    elif inherit_bill:
        from apps.purchasing.models import Bill
        try:
            bill = Bill.objects.get(pk=int(inherit_bill))
        except (Bill.DoesNotExist, ValueError):
            return Response({'inherit_bill': ['Not found.']}, status=status.HTTP_400_BAD_REQUEST)
        associate_with = {'bill': bill}

    attachments = []
    for uploaded in request.FILES.getlist('attachments'):
        attachments.append((
            uploaded.name, uploaded.read(),
            uploaded.content_type or 'application/octet-stream',
        ))

    try:
        record = OutboundEmailService.send_tracked(
            to=to, subject=subject, body=body,
            cc=cc, bcc=bcc, attachments=attachments,
            associate_with=associate_with,
            in_reply_to=in_reply_to or None,
            references=references or None,
        )
    except Exception as e:
        return Response(
            {'detail': str(e)},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response({'email_record_id': record.email_record_id})


def _stub_501(endpoint):
    @api_view(['POST'])
    @permission_classes([IsAuthenticated])
    def view(request, *args, **kwargs):
        return Response(
            {'detail': 'Not yet implemented.', 'endpoint': endpoint},
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )
    return view
