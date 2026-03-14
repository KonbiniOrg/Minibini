from rest_framework import viewsets
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.api.mixins import StatusTransitionMixin
from .serializers import JobSerializer


class JobViewSet(StatusTransitionMixin, viewsets.ModelViewSet):
    queryset = Job.objects.all().order_by('-created_date')
    serializer_class = JobSerializer
    lookup_field = 'pk'

    def get_queryset(self):
        qs = super().get_queryset()
        contact = self.request.query_params.get('contact')
        if contact:
            qs = qs.filter(contact_id=contact)
        return qs

    status_actions = {
        'complete': {'service': lambda pk: JobService.update_job(pk, status='completed')},
        'cancel': {
            'service': lambda pk, reason=None: JobService.update_job(pk, status='cancelled'),
            'requires_reason': True,
        },
        'reopen': {
            'service': lambda pk, reason=None: JobService.update_job(pk, status='draft'),
            'requires_reason': True,
        },
    }

    def perform_create(self, serializer):
        data = serializer.validated_data
        job = JobService.create_job(**data)
        serializer.instance = job

    def perform_update(self, serializer):
        job = JobService.update_job(self.get_object().pk, **serializer.validated_data)
        serializer.instance = job
