from django.template.loader import render_to_string
from weasyprint import HTML


def generate_purchase_order_pdf(po):
    """
    Generate a PDF for a purchase order.
    Returns bytes containing the PDF.
    """
    line_items = po.purchaseorderlineitem_set.select_related(
        'accounting_category', 'price_list_item'
    ).order_by('line_number')

    total = sum(item.total_amount for item in line_items)

    business_name = po.business.business_name if po.business else ''
    contact_name = ''
    if po.contact:
        contact_name = f"{po.contact.first_name} {po.contact.last_name}"

    html_string = render_to_string('purchasing/purchase_order_pdf.html', {
        'po': po,
        'business_name': business_name,
        'contact_name': contact_name,
        'line_items': line_items,
        'total': total,
    })

    return HTML(string=html_string).write_pdf()
