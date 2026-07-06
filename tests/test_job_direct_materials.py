"""Task 2.2: Direct Material creation on a Job at any non-terminal status.

Tests that:
  - MaterialService.create_on_job creates a catalog-backed Material on a DRAFT
    job, inheriting sell_price/unit_cost from the InventoryItem via _populate_from_pli.
  - MaterialService.create_on_job creates a freeform Material (no inventory_item)
    on a DRAFT job.
  - The on_hold guard still rejects Material creation on an on_hold job.
  - POST /api/jobs/{id}/materials/ returns 201 on a DRAFT job for both a catalog
    pick and a freeform material.
  - The endpoint is IsAuthenticated only (any authenticated user may add materials);
    unauthenticated requests are rejected with 403.

What existed vs. what was added (Task 2.2):
  EXISTED: MaterialService.create_on_job — gates only on on_hold; draft is fine.
  EXISTED: POST /api/jobs/{id}/materials/ (create_material action in JobViewSet)
           with permission_classes=[IsAuthenticated].
  ADDED: This test module verifying draft-job behaviour on both paths.

Permission rationale:
  CLAUDE.md's atom table lists `can_manage_financials` for invoices/POs/bills/PLIs
  but NOT for job Materials.  The existing endpoint (apps/api/jobs/views.py
  create_material) and MaterialViewSet both use IsAuthenticated only, matching the
  design intent that any worker can add/draw materials against a job (same carve-out
  as adding tasks).  This test confirms that choice.

TDD evidence:
  Both service and endpoint were already implemented on the branch.  The first
  run is expected to be GREEN (no fabricated RED).  The test file itself is the
  deliverable — it crystallises the contract and guards against future regressions.

Note on state-bypass in setUp:
  Job.objects.create(status=X) bypasses the state-machine transition check
  (self.pk is None at creation time, so full_clean skips the guard).  This is the
  established test pattern — see test_materialize_worksheet.py and
  test_job_direct_tasks.py.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, User
from apps.inventory.models import InventoryItem, Material
from apps.inventory.services import MaterialService
from apps.jobs.models import Job


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cat(code, name=None):
    ac, _ = AccountingCategory.objects.get_or_create(
        code=code, defaults={'name': name or f'AC {code}'},
    )
    return ac


def _make_pli(code, cat, *, purchase_price='10.00', selling_price='15.00'):
    return InventoryItem.objects.create(
        code=code,
        description=f'Widget {code}',
        accounting_category=cat,
        purchase_price=Decimal(purchase_price),
        selling_price=Decimal(selling_price),
        units='ea',
    )


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------

class DirectMaterialCreateServiceTest(TestCase):
    """Unit tests for MaterialService.create_on_job on a draft job."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name='Matl', last_name='Svc')
        self.cat = _make_cat('DM-SVC', 'Direct Matl Svc AC')
        self.job = Job.objects.create(
            job_number='DM-SVC-001',
            name='Draft Matl Job',
            contact=self.contact,
            status=Job.STATUS_DRAFT,
        )
        self.pli = _make_pli('DM-SVC-PLI', self.cat,
                              purchase_price='10.00', selling_price='15.00')

    def test_catalog_backed_material_on_draft_job(self):
        """create_on_job creates a catalog-backed Material on a DRAFT job and
        inherits sell_price / unit_cost from the InventoryItem via _populate_from_pli."""
        m = MaterialService.create_on_job(
            job=self.job,
            inventory_item=self.pli,
            quantity=Decimal('3.00'),
        )
        self.assertIsNotNone(m.pk)
        self.assertEqual(m.job, self.job)
        self.assertIsNone(m.task)
        self.assertEqual(m.inventory_item, self.pli)
        self.assertEqual(
            m.sell_price, Decimal('15.00'),
            'sell_price should be inherited from InventoryItem.selling_price',
        )
        self.assertEqual(
            m.unit_cost, Decimal('10.00'),
            'unit_cost should be inherited from InventoryItem.purchase_price',
        )
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)

    def test_freeform_material_on_draft_job(self):
        """create_on_job creates a freeform Material (no inventory_item) on a DRAFT job."""
        m = MaterialService.create_on_job(
            job=self.job,
            description='Freeform Widget',
            quantity=Decimal('2.00'),
            units='lbs',
            accounting_category=self.cat,
        )
        self.assertIsNotNone(m.pk)
        self.assertEqual(m.job, self.job)
        self.assertIsNone(m.inventory_item)
        self.assertEqual(m.description, 'Freeform Widget')
        self.assertEqual(m.units, 'lbs')
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)

    def test_on_hold_job_is_rejected(self):
        """create_on_job raises ValidationError on an on_hold job."""
        job = Job.objects.create(
            job_number='DM-SVC-HOLD',
            contact=self.contact,
            status=Job.STATUS_ON_HOLD,
        )
        with self.assertRaises(ValidationError):
            MaterialService.create_on_job(
                job=job,
                description='Blocked',
                quantity=Decimal('1.00'),
                accounting_category=self.cat,
            )

    def test_catalog_material_attached_to_job(self):
        """The created Material is queryable via job.materials (FK)."""
        MaterialService.create_on_job(
            job=self.job,
            inventory_item=self.pli,
            quantity=Decimal('1.00'),
        )
        self.assertEqual(Material.objects.filter(job=self.job).count(), 1)


# ---------------------------------------------------------------------------
# API-level tests
# ---------------------------------------------------------------------------

class DirectMaterialCreateAPITest(TestCase):
    """API tests for POST /api/jobs/{id}/materials/ on a draft job."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='dmworker', password='testpass')
        self.client.force_authenticate(user=self.user)

        self.contact = Contact.objects.create(first_name='API', last_name='Matl')
        self.cat = _make_cat('DM-API', 'Direct Matl API AC')
        self.job = Job.objects.create(
            job_number='DM-API-001',
            name='Draft Matl API Job',
            contact=self.contact,
            status=Job.STATUS_DRAFT,
        )
        self.pli = _make_pli('DM-API-PLI', self.cat,
                              purchase_price='8.00', selling_price='12.00')

    def _url(self):
        return f'/api/jobs/{self.job.pk}/materials/'

    def test_post_catalog_material_on_draft_job_returns_201(self):
        """POST /api/jobs/{id}/materials/ with an InventoryItem on a DRAFT job
        returns 201 and the Material inherits sell_price from the InventoryItem."""
        resp = self.client.post(self._url(), {
            'inventory_item': self.pli.pk,
            'quantity': '4.00',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        m = Material.objects.get(job=self.job, inventory_item=self.pli)
        self.assertEqual(
            m.sell_price, Decimal('12.00'),
            'catalog material should inherit sell_price from InventoryItem',
        )
        self.assertEqual(
            m.unit_cost, Decimal('8.00'),
            'catalog material should inherit unit_cost from InventoryItem',
        )

    def test_post_freeform_material_on_draft_job_returns_201(self):
        """POST /api/jobs/{id}/materials/ freeform (no inventory_item) on a
        DRAFT job returns 201."""
        resp = self.client.post(self._url(), {
            'description': 'Freeform via API',
            'quantity': '1.00',
            'units': 'lbs',
            'accounting_category': self.cat.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        m = Material.objects.get(job=self.job, description='Freeform via API')
        self.assertIsNone(m.inventory_item)
        self.assertEqual(m.units, 'lbs')

    def test_post_material_unauthenticated_returns_403(self):
        """Unauthenticated POST is rejected with 403."""
        self.client.force_authenticate(user=None)
        resp = self.client.post(self._url(), {
            'description': 'Sneaky',
            'quantity': '1.00',
            'accounting_category': self.cat.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_post_material_any_authenticated_user_succeeds(self):
        """Any authenticated user may add a Material to a job (IsAuthenticated only —
        no can_manage_financials or can_manage_jobs atom required)."""
        other = User.objects.create_user(username='dmother', password='testpass')
        self.client.force_authenticate(user=other)
        resp = self.client.post(self._url(), {
            'description': 'Worker Material',
            'quantity': '1.00',
            'units': 'none',
            'accounting_category': self.cat.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
