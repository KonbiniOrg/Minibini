from django.db.models import Q

from apps.core.models import HistoryEntry


def build_job_history(job):
    """Collate a Job's history across its related records.

    Returns (queryset, source_labels, source_links), where the label/link
    dicts are keyed by (object_type, object_id). ChangeOrder uses the single
    object_type 'changeorder' (normalized earlier).
    """
    from apps.estimates.models import Estimate, ChangeOrder
    from apps.invoicing.models import Invoice
    from apps.jobs.models import Task
    from apps.deliverables.models import Deliverable, Shipment
    from apps.inventory.models import Material

    estimates = list(Estimate.objects.filter(job=job))
    change_orders = list(ChangeOrder.objects.filter(job=job))
    invoices = list(Invoice.objects.filter(job=job))
    tasks = list(Task.objects.filter(job=job))
    deliverables = list(Deliverable.objects.filter(job=job))
    shipments = list(Shipment.objects.filter(job=job))
    materials = list(Material.objects.filter(job=job))

    q = Q(object_type='job', object_id=job.pk)

    def add(object_type, objs):
        nonlocal q
        ids = [o.pk for o in objs]
        if ids:
            q |= Q(object_type=object_type, object_id__in=ids)

    add('estimate', estimates)
    add('changeorder', change_orders)
    add('invoice', invoices)
    add('task', tasks)
    add('deliverable', deliverables)
    add('shipment', shipments)
    add('material', materials)

    labels = {}
    links = {}

    def reg(object_type, obj_id, label, link=None):
        labels[(object_type, obj_id)] = label
        links[(object_type, obj_id)] = link

    reg('job', job.pk, f'Job {job.job_number}', f'#/jobs/{job.pk}')
    for e in estimates:
        reg('estimate', e.pk, f'Estimate {e.estimate_number}', f'#/estimates/{e.pk}')
    for c in change_orders:
        reg('changeorder', c.pk, f'Change Order {c.change_order_number}')
    for inv in invoices:
        reg('invoice', inv.pk, f'Invoice {inv.invoice_number}', f'#/invoices/{inv.pk}')
    for t in tasks:
        reg('task', t.pk, f'Task: {t.name}', f'#/jobs/{job.pk}/tasks/{t.pk}')
    for d in deliverables:
        reg('deliverable', d.pk, f'Deliverable: {d.description[:40]}')
    for s in shipments:
        # No per-shipment page; point at the job's shipments matrix.
        reg('shipment', s.pk, f'Shipment #{s.sequence}', f'#/jobs/{job.pk}/shipments')
    for m in materials:
        reg('material', m.pk, f'Material: {m.description[:40]}')

    qs = HistoryEntry.objects.filter(q).select_related('user')
    return qs, labels, links
