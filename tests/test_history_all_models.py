from django.test import TestCase
from apps.jobs.models import Job
from apps.estimates.models import Estimate, EstWorksheet
from apps.invoicing.models import Invoice
from apps.purchasing.models import PurchaseOrder, Bill
from apps.contacts.models import Contact, Business


class AllTrackedModelsTest(TestCase):
    TRACKED_MODELS = [
        Job, Estimate, EstWorksheet,
        Invoice, PurchaseOrder, Bill, Contact, Business,
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
