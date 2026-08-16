"""Acceptance crystallizes hand-lines into atoms (replaces worksheet carry-over).

Triggered when an Estimate transitions to ACCEPTED (see apps/estimates/signals.py).
In the job-owns-atoms model, work already lives on the Job (Tasks/Materials created
directly), so there is nothing to copy from a worksheet. Instead, acceptance:

  1. For each accepted-estimate line item with NO source row (a hand-line) that is
     not a percentage adjustment, crystallizes it onto the job:
       - a hand-line with a `service_item` → becomes a **Task**;
       - a hand-line with an `inventory_item` (added via "From Inventory") is a
         catalog material → becomes a **Material** atom;
       - a bare hand-line marked `is_material=True` → becomes an **established
         Material** (QOH-0 lot minted at a reverse-markup placeholder cost,
         cost_source='estimated');
       - any other hand-line (a plain line) → crystallizes NOTHING: no atom, no
         source row — it stays a document-only line.
     Crystallized lines are source-linked to the atom they created.
  2. Earmarks the job's inventoried materials.

Atom-backed lines (those with an EstimateLineItemSource) already have their
Tasks/Materials on the job — nothing to convert. Adjustment lines stay
document-only (they recompute against the live lines).
"""
from decimal import Decimal
from django.db import transaction


class EstimateAcceptanceService:

    @staticmethod
    @transaction.atomic
    def on_accept(estimate):
        """Crystallize the estimate's hand-lines into atoms, then earmark the job.

        Discriminator order: service_item → Task, inventory_item → Material,
        is_material (bare) → established Material (reverse-markup), else → skip
        (plain lines stay document-only; no atom, no source row).
        Finishes by calling JobService.maybe_auto_release — an all-catalog
        estimate crystallizes every line here, so the checklist can already
        be fully answered by the time this returns.
        Returns: {'materials_created': int, 'tasks_created': int}
        """
        from apps.inventory.services import InventoryService, MaterialService

        job = estimate.job
        # A sibling signal (estimate_status_changed_for_job) approves the job just
        # before this fires; refresh so we act against committed state.
        job.refresh_from_db()

        from apps.estimates.models import EstimateLineItemSource

        materials_created = 0
        tasks_created = 0
        for li in estimate.estimatelineitem_set.all():
            if li.sources.exists():              # atom-backed → already on the job
                continue
            if li.adjustment_service_id is not None:  # percentage adjustments stay document-only
                continue

            if li.service_item_id is not None:
                task = li.service_item.generate_task(
                    job, est_qty=li.qty or Decimal('1'),
                    description=li.description or '',
                    allow_inactive_scheme=True,
                )
                EstimateLineItemSource.objects.create(
                    estimate_line_item=li,
                    source_type=EstimateLineItemSource.SOURCE_TASK,
                    source_pk=task.pk,
                )
                tasks_created += 1
                continue

            if li.inventory_item_id is not None:
                # Catalog material hand-line → Material atom. The PLI supplies cost
                # (via _populate_from_pli); the estimate's price is the sell price.
                material = MaterialService.create_on_job(
                    job=job,
                    task=None,
                    description=li.description or '',
                    quantity=li.qty or Decimal('1'),
                    sell_price=li.price or Decimal('0'),
                    inventory_item=li.inventory_item,
                    accounting_category=li.accounting_category,
                    units=li.units or 'none',
                )
                EstimateLineItemSource.objects.create(
                    estimate_line_item=li,
                    source_type=EstimateLineItemSource.SOURCE_MATERIAL,
                    source_pk=material.pk,
                )
                materials_created += 1
                continue

            # Bare line marked as a material → Material atom, ESTABLISHED with a
            # reverse-markup placeholder cost (see
            # MaterialService.establish_reverse_markup — shared with CO
            # acceptance so both documents crystallize identically).
            # (pinned discriminator): the service_item branch sits above inventory_item;
            # this is_material branch stays last — anything below it is skipped.
            if li.is_material:
                material = MaterialService.create_on_job(
                    job=job,
                    task=None,
                    description=li.description or '',
                    quantity=li.qty or Decimal('1'),
                    sell_price=li.price or Decimal('0'),
                    inventory_item=None,
                    accounting_category=li.accounting_category,
                    units=li.units or 'none',
                )
                material = MaterialService.establish_reverse_markup(material)
                EstimateLineItemSource.objects.create(
                    estimate_line_item=li,
                    source_type=EstimateLineItemSource.SOURCE_MATERIAL,
                    source_pk=material.pk,
                )
                materials_created += 1
                continue

            # Plain hand-line (no service_item, no inventory_item, not marked
            # material): stays a document-only line. No atom, no source row.

        InventoryService.create_earmarks_for_job(job)

        # An all-catalog estimate crystallizes every line above, leaving
        # nothing unanswered — the job releases to the floor right here.
        from apps.jobs.services import JobService
        JobService.maybe_auto_release(job)

        return {'materials_created': materials_created, 'tasks_created': tasks_created}
