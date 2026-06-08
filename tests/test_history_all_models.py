from django.test import TestCase
from apps.jobs.models import Job, Task
from apps.estimates.models import Estimate, EstWorksheet
from apps.invoicing.models import Invoice
from apps.purchasing.models import PurchaseOrder, Bill
from apps.contacts.models import Contact, Business
from apps.inventory.models import Material
from apps.deliverables.models import Deliverable, Shipment


class AllTrackedModelsTest(TestCase):
    TRACKED_MODELS = [
        Job, Task, Estimate, EstWorksheet,
        Invoice, PurchaseOrder, Bill, Contact, Business,
        Material, Deliverable, Shipment,
    ]

    def test_all_models_are_tracked(self):
        for model in self.TRACKED_MODELS:
            with self.subTest(model=model.__name__):
                self.assertTrue(
                    getattr(model, '_history_tracked', False),
                    f'{model.__name__} is not decorated with @history'
                )

    def test_all_models_have_exclude_set(self):
        for model in self.TRACKED_MODELS:
            with self.subTest(model=model.__name__):
                self.assertIsInstance(
                    getattr(model, '_history_exclude', None),
                    set,
                    f'{model.__name__} missing _history_exclude'
                )

    def test_pk_fields_excluded(self):
        expected = {
            Task: 'task_id',
            Material: 'material_id',
            Deliverable: 'id',
            Shipment: 'id',
        }
        for model, pk in expected.items():
            with self.subTest(model=model.__name__):
                self.assertIn(pk, model._history_exclude)
