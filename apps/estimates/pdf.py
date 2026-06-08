from django.template.loader import render_to_string
from weasyprint import HTML


def generate_estimate_pdf(estimate):
    """Generate a PDF for an estimate. Returns bytes."""
    line_items = estimate.estimatelineitem_set.select_related(
        'accounting_category',
    ).order_by('line_number')

    total = sum(item.total_amount for item in line_items)

    job = estimate.job
    contact = job.contact if job else None
    business_name = ''
    contact_name = ''
    if contact:
        contact_name = f'{contact.first_name} {contact.last_name}'.strip()
        if contact.business:
            business_name = contact.business.business_name

    html_string = render_to_string('estimates/estimate_pdf.html', {
        'estimate': estimate,
        'job': job,
        'business_name': business_name,
        'contact_name': contact_name,
        'line_items': line_items,
        'total': total,
    })
    return HTML(string=html_string).write_pdf()


def generate_change_order_pdf(co):
    """Generate a PDF for a change order. Returns bytes.

    Renders the before/after diff (the same `compose_change_order_diff` the
    customer portal shows), so the document spells out what the change adds,
    removes, or revises against the accepted estimate, plus the prior/new
    totals."""
    from apps.estimates.agreement import compose_change_order_diff

    diff = compose_change_order_diff(co)

    job = co.job
    contact = job.contact if job else None
    business_name = ''
    contact_name = ''
    if contact:
        contact_name = f'{contact.first_name} {contact.last_name}'.strip()
        if contact.business:
            business_name = contact.business.business_name

    html_string = render_to_string('estimates/change_order_pdf.html', {
        'co': co,
        'job': job,
        'business_name': business_name,
        'contact_name': contact_name,
        'estimate_number': co.estimate.estimate_number if co.estimate_id else '',
        'line_rows': diff['line_rows'],
        'prior_total': diff['prior_total'],
        'proposed_total': diff['proposed_total'],
        'diff_total': diff['diff_total'],
    })
    return HTML(string=html_string).write_pdf()
