from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework import serializers, viewsets, status
from apps.core.models import User
from apps.core.services import ServiceError
from apps.api.mixins import StatusTransitionMixin
from tests.base import BaseTestCase


class StatusTransitionMixinTest(BaseTestCase):
    """Test StatusTransitionMixin auto-registers action endpoints."""

    def setUp(self):
        super().setUp()
        self.user = User.objects.get(username='admin')
        self.factory = APIRequestFactory()

    def test_routine_action_calls_service(self):
        """A routine status action should call the service method and return the updated object."""
        from apps.jobs.models import Job

        class JobSerializer(serializers.ModelSerializer):
            class Meta:
                model = Job
                fields = ['job_id', 'status']

        class TestViewSet(StatusTransitionMixin, viewsets.ModelViewSet):
            queryset = Job.objects.all()
            serializer_class = JobSerializer
            lookup_field = 'pk'
            status_actions = {
                'complete': {'service': lambda pk: Job.objects.filter(pk=pk).update(status='completed')},
            }

        view = TestViewSet.as_view({'post': 'complete'}, detail=True)
        job = Job.objects.first()
        request = self.factory.post(f'/api/jobs/{job.pk}/complete/')
        force_authenticate(request, user=self.user)
        response = view(request, pk=job.pk)
        self.assertEqual(response.status_code, 200)

    def test_exceptional_action_requires_reason(self):
        """An exceptional action (requires_reason=True) should reject requests without a reason."""
        from apps.jobs.models import Job

        class JobSerializer(serializers.ModelSerializer):
            class Meta:
                model = Job
                fields = ['job_id', 'status']

        class TestViewSet(StatusTransitionMixin, viewsets.ModelViewSet):
            queryset = Job.objects.all()
            serializer_class = JobSerializer
            lookup_field = 'pk'
            status_actions = {
                'cancel': {
                    'service': lambda pk, reason=None: Job.objects.filter(pk=pk).update(status='cancelled'),
                    'requires_reason': True,
                },
            }

        view = TestViewSet.as_view({'post': 'cancel'}, detail=True)
        job = Job.objects.first()

        # Without reason — should fail
        request = self.factory.post(f'/api/jobs/{job.pk}/cancel/', {}, format='json')
        force_authenticate(request, user=self.user)
        response = view(request, pk=job.pk)
        self.assertEqual(response.status_code, 400)

        # With reason — should succeed
        request = self.factory.post(f'/api/jobs/{job.pk}/cancel/', {'reason': 'Test cancellation'}, format='json')
        force_authenticate(request, user=self.user)
        response = view(request, pk=job.pk)
        self.assertEqual(response.status_code, 200)

    def test_service_error_returns_400(self):
        """ServiceError from the service method should return 400."""
        from apps.jobs.models import Job

        def failing_service(pk):
            raise ServiceError("Cannot complete this job")

        class JobSerializer(serializers.ModelSerializer):
            class Meta:
                model = Job
                fields = ['job_id', 'status']

        class TestViewSet(StatusTransitionMixin, viewsets.ModelViewSet):
            queryset = Job.objects.all()
            serializer_class = JobSerializer
            lookup_field = 'pk'
            status_actions = {
                'complete': {'service': failing_service},
            }

        view = TestViewSet.as_view({'post': 'complete'}, detail=True)
        job = Job.objects.first()
        request = self.factory.post(f'/api/jobs/{job.pk}/complete/')
        force_authenticate(request, user=self.user)
        response = view(request, pk=job.pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn('Cannot complete this job', str(response.data))
