from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from weasyprint import HTML

from apps.core.pdf_branding import render_document_html


def render_purchase_order_html(po):
    """The purchase order document as an HTML string (what WeasyPrint
    renders)."""
    line_items = list(po.purchaseorderlineitem_set.select_related(
        'accounting_category', 'inventory_item'
    ).order_by('line_number'))
    # Code column: the catalog code, blank for freeform lines and for minted
    # LOT-* lots (a lot id means nothing to the vendor).
    for li in line_items:
        code = li.inventory_item.code if li.inventory_item_id else ''
        li.display_code = '' if code.startswith('LOT-') else code

    total = sum(item.total_amount for item in line_items)

    business_name = po.business.business_name if po.business else ''
    contact = po.contact
    contact_name = ''
    if contact:
        contact_name = f"{contact.first_name} {contact.last_name}"
    contact_business = ''
    if contact and contact.business:
        contact_business = contact.business.business_name

    return render_document_html('purchasing/purchase_order_pdf.html', 'po', {
        'po': po,
        'business_name': business_name,
        'contact_name': contact_name,
        'line_items': line_items,
        'total': total,
    }, {
        'contact_fname': contact.first_name if contact else '',
        'contact_lname': contact.last_name if contact else '',
        'contact_business': contact_business,
        'document_number': po.po_number,
        'po_number': po.po_number,
        'vendor_name': business_name,
    })


def generate_purchase_order_pdf(po):
    """
    Generate a PDF for a purchase order.
    Returns bytes containing the PDF.
    """
    return HTML(string=render_purchase_order_html(po)).write_pdf()


def preview_purchase_order_html(drafts=None):
    """A sample purchase order as an HTML string for the settings preview,
    branded with the saved settings overlaid by `drafts` (the form's unsaved
    values). Touches no real PurchaseOrder."""
    today = date.today()
    lines = [
        SimpleNamespace(line_number=1, description='Sample material line',
                        display_code='SAMPLE-01', vendor_sku='V-1000',
                        qty=Decimal('10'), units='ea', price=Decimal('4.25'),
                        total_amount=Decimal('42.50')),
    ]
    return render_document_html('purchasing/purchase_order_pdf.html', 'po', {
        'po': SimpleNamespace(
            po_number='PO-0000', issued_date=today, created_date=today,
            requested_date=None),
        'business_name': 'Sample Vendor Inc.',
        'contact_name': 'Jordan Sample',
        'line_items': lines,
        'total': sum(line.total_amount for line in lines),
    }, {
        'contact_fname': 'Jordan',
        'contact_lname': 'Sample',
        'contact_business': 'Sample Vendor Inc.',
        'document_number': 'PO-0000',
        'po_number': 'PO-0000',
        'vendor_name': 'Sample Vendor Inc.',
    }, drafts)
