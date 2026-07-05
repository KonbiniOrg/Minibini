from rest_framework.test import APIRequestFactory, force_authenticate
from apps.core.models import JobHistory
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
                'complete': {'service': lambda pk: Job.objects.filter(pk=pk).update(status=Job.STATUS_COMPLETED)},
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
                    'service': lambda pk, reason=None: Job.objects.filter(pk=pk).update(status=Job.STATUS_CANCELLED),
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

    def test_reason_persisted_to_history(self):
        """When requires_reason=True, the reason should be saved as a ."""
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
                    'service': lambda pk, reason=None: Job.objects.filter(pk=pk).update(status=Job.STATUS_CANCELLED),
                    'requires_reason': True,
                },
            }

        view = TestViewSet.as_view({'post': 'cancel'}, detail=True)
        job = Job.objects.first()

        request = self.factory.post(
            f'/api/jobs/{job.pk}/cancel/',
            {'reason': 'Client withdrew request'},
            format='json',
        )
        force_authenticate(request, user=self.user)
        # APIRequestFactory skips middleware, so provide the HistoryContext the
        # history middleware would set — record_history attributes from it.
        from apps.core.history import HistoryContext, set_history_context
        set_history_context(HistoryContext(user=self.user))
        self.addCleanup(set_history_context, None)
        response = view(request, pk=job.pk)
        self.assertEqual(response.status_code, 200)

        entry = JobHistory.objects.filter(
            entry_type='audit',
            object_type='job',
            object_id=job.pk,
            text='Client withdrew request',
        ).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.user, self.user)
        # Verify no separate action entry was created
        action_count = JobHistory.objects.filter(
            entry_type='action', object_type='job', object_id=job.pk,
        ).count()
        self.assertEqual(action_count, 0)

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
