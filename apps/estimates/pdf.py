from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from weasyprint import HTML

from apps.core.pdf_branding import render_document_html


def _pdf_party_context(job):
    """business_name / contact_name for a document PDF's header block,
    resolved from the job's contact. Shared by the estimate and change-order
    generators."""
    contact = job.contact if job else None
    business_name = ''
    contact_name = ''
    if contact:
        contact_name = f'{contact.first_name} {contact.last_name}'.strip()
        if contact.business:
            business_name = contact.business.business_name
    return {'business_name': business_name, 'contact_name': contact_name}


def _pdf_text_values(job, document_number, **extra):
    """Placeholder values for a job document's PDF text slots — the email
    templates' common set, minus the sender (a PDF has no sending user)."""
    contact = job.contact if job else None
    contact_business = ''
    if contact and contact.business:
        contact_business = contact.business.business_name
    return {
        'contact_fname': contact.first_name if contact else '',
        'contact_lname': contact.last_name if contact else '',
        'contact_business': contact_business,
        'job_number': job.job_number if job else '',
        'job_name': job.name if job else '',
        'document_number': document_number,
        **extra,
    }


def render_estimate_html(estimate):
    """The estimate document as an HTML string (what WeasyPrint renders)."""
    from apps.core.email_templates import build_object_url

    line_items = estimate.estimatelineitem_set.select_related(
        'accounting_category',
    ).order_by('line_number')

    total = sum(item.total_amount for item in line_items)

    job = estimate.job

    return render_document_html('estimates/estimate_pdf.html', 'estimate', {
        'estimate': estimate,
        'job': job,
        **_pdf_party_context(job),
        'line_items': line_items,
        'total': total,
    }, _pdf_text_values(
        job, estimate.estimate_number,
        estimate_number=estimate.estimate_number,
        object_url=build_object_url('estimate', estimate.estimate_id),
    ))


def generate_estimate_pdf(estimate):
    """Generate a PDF for an estimate. Returns bytes."""
    return HTML(string=render_estimate_html(estimate)).write_pdf()


def render_change_order_html(co):
    """The change order document as an HTML string.

    Renders the before/after diff (the same `compose_change_order_diff` the
    customer portal shows), so the document spells out what the change adds,
    removes, or revises against the accepted estimate, plus the prior/new
    totals."""
    from apps.core.email_templates import build_object_url
    from apps.estimates.agreement import compose_change_order_diff
    from apps.estimates.change_order_service import ChangeOrderService

    diff = compose_change_order_diff(co)
    deliverable_rows = ChangeOrderService.compose_deliverable_diff(co)

    job = co.job
    estimate_number = co.estimate.estimate_number if co.estimate_id else ''

    return render_document_html('estimates/change_order_pdf.html', 'change_order', {
        'co': co,
        'job': job,
        **_pdf_party_context(job),
        'estimate_number': estimate_number,
        'deliverable_rows': deliverable_rows,
        'line_rows': diff['line_rows'],
        'prior_total': diff['prior_total'],
        'proposed_total': diff['proposed_total'],
        'diff_total': diff['diff_total'],
    }, _pdf_text_values(
        job, co.change_order_number,
        change_order_number=co.change_order_number,
        estimate_number=estimate_number,
        object_url=build_object_url('change_order', co.pk),
    ))


def generate_change_order_pdf(co):
    """Generate a PDF for a change order. Returns bytes."""
    return HTML(string=render_change_order_html(co)).write_pdf()


# --- Settings previews -------------------------------------------------------
# Sample documents rendered through the real templates with the saved
# branding, so a config user can check the letterhead and text slots without
# sending anything. Nothing here touches a real Estimate / ChangeOrder.

_SAMPLE_PARTY = {'business_name': 'Sample Customer Co.', 'contact_name': 'Alex Sample'}
_SAMPLE_JOB = SimpleNamespace(job_number='JOB-0000', name='Sample job')
_SAMPLE_VALUES = {
    'contact_fname': 'Alex',
    'contact_lname': 'Sample',
    'contact_business': 'Sample Customer Co.',
    'job_number': _SAMPLE_JOB.job_number,
    'job_name': _SAMPLE_JOB.name,
    'object_url': 'https://example.com/portal/?token=sample',
}


def preview_estimate_pdf():
    """A sample estimate PDF using the saved branding. Returns bytes."""
    today = date.today()
    lines = [
        SimpleNamespace(line_number=1, description='Sample service line',
                        qty=Decimal('2'), units='hr', price=Decimal('85.00'),
                        total_amount=Decimal('170.00')),
        SimpleNamespace(line_number=2, description='Sample material line',
                        qty=Decimal('4'), units='ea', price=Decimal('12.50'),
                        total_amount=Decimal('50.00')),
    ]
    html = render_document_html('estimates/estimate_pdf.html', 'estimate', {
        'estimate': SimpleNamespace(
            estimate_number='EST-0000', sent_date=today, created_date=today,
            expiration_date=None),
        'job': _SAMPLE_JOB,
        **_SAMPLE_PARTY,
        'line_items': lines,
        'total': sum(line.total_amount for line in lines),
    }, {**_SAMPLE_VALUES, 'document_number': 'EST-0000', 'estimate_number': 'EST-0000'})
    return HTML(string=html).write_pdf()


def preview_change_order_pdf():
    """A sample change order PDF using the saved branding. Returns bytes."""
    today = date.today()
    html = render_document_html('estimates/change_order_pdf.html', 'change_order', {
        'co': SimpleNamespace(
            change_order_number='CO-0000', sent_date=today, created_date=today,
            expiration_date=None),
        'job': _SAMPLE_JOB,
        **_SAMPLE_PARTY,
        'estimate_number': 'EST-0000',
        'deliverable_rows': [],
        'line_rows': [
            {'kind': 'unchanged', 'line_number': 1,
             'description': 'Sample existing line', 'qty': Decimal('2'),
             'units': 'hr', 'price': Decimal('85.00'), 'amount': Decimal('170.00')},
            {'kind': 'added', 'line_number': 2,
             'description': 'Sample added line', 'qty': Decimal('1'),
             'units': 'ea', 'price': Decimal('40.00'), 'amount': Decimal('40.00')},
        ],
        'prior_total': Decimal('170.00'),
        'proposed_total': Decimal('210.00'),
        'diff_total': Decimal('40.00'),
    }, {
        **_SAMPLE_VALUES, 'document_number': 'CO-0000',
        'change_order_number': 'CO-0000', 'estimate_number': 'EST-0000',
    })
    return HTML(string=html).write_pdf()
