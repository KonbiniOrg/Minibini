from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.core.models import EmailRecord
from apps.core.services import EmailService, ServiceError, NotFoundError
from apps.api.permissions import CanManageJobs
from .serializers import EmailRecordSerializer


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def email_list(request):
    emails = EmailRecord.objects.select_related('temp_data').order_by('-created_at')
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
    from apps.jobs.services import JobService
    try:
        email = EmailRecord.objects.select_related('temp_data').get(pk=pk)
    except EmailRecord.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    contact_id = request.data.get('contact')
    name = request.data.get('name', '')
    if not contact_id:
        return Response(
            {'contact': ['This field is required.']},
            status=status.HTTP_400_BAD_REQUEST,
        )

    job = JobService.create_job(name=name, contact_id=contact_id)
    EmailService.associate_with_job(pk, job.pk)
    return Response({
        'job_id': job.pk,
        'job_number': job.job_number,
    }, status=status.HTTP_201_CREATED)


def _stub_501(endpoint):
    @api_view(['POST'])
    @permission_classes([IsAuthenticated])
    def view(request, *args, **kwargs):
        return Response(
            {'detail': 'Not yet implemented.', 'endpoint': endpoint},
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )
    return view
