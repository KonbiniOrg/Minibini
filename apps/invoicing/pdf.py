from django.template.loader import render_to_string
from weasyprint import HTML


def generate_job_statement_pdf(invoice):
    """
    Generate a job statement PDF for an invoice.
    Returns bytes containing the PDF.
    """
    line_items = invoice.invoicelineitem_set.select_related(
        'accounting_category', 'inventory_item'
    ).order_by('line_number')

    subtotal = sum(item.total_amount for item in line_items)

    job = invoice.job
    business_name = ''
    if job.contact and job.contact.business:
        business_name = job.contact.business.business_name

    html_string = render_to_string('invoicing/job_statement.html', {
        'invoice': invoice,
        'job': job,
        'business_name': business_name,
        'line_items': line_items,
        'subtotal': subtotal,
    })

    return HTML(string=html_string).write_pdf()
