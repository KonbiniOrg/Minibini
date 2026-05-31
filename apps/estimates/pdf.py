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
