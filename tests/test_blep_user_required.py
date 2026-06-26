from django.core.exceptions import ValidationError

from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Job, Task, Blep


class BlepUserRequiredTest(BaseTestCase):
    """A logged time entry must belong to a worker — `user` is non-nullable."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='Task', job=self.job, service_item_id=1)
        self.user = User.objects.get(username='admin')

    def test_blep_without_user_fails_validation(self):
        blep = Blep(task=self.task, user=None)
        with self.assertRaises(ValidationError) as ctx:
            blep.full_clean()
        self.assertIn('user', ctx.exception.message_dict)

    def test_blep_with_user_passes_validation(self):
        blep = Blep(task=self.task, user=self.user)
        blep.full_clean()  # must not raise
