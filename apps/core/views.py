from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.urls import reverse
from .models import User, AccountingCategory, Configuration, EmailRecord, TempEmail
from .services import EmailService, ConfigurationService, NotFoundError
from .email_utils import parse_email_address, extract_company_from_signature, extract_email_body
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job
from .forms import AccountingCategoryForm, TaxConfigurationForm


@login_required
@permission_required('core.can_manage_config', raise_exception=True)
def user_list(request):
    users = User.objects.all().order_by('username')
    return render(request, 'core/user_list.html', {'users': users})


@login_required
@permission_required('core.can_manage_config', raise_exception=True)
def user_detail(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    return render(request, 'core/user_detail.html', {'user': user})

@login_required
@permission_required('core.can_manage_jobs', raise_exception=True)
def email_inbox(request):
    """
    Display list of emails with temporary metadata.
    Fetches new emails since latest_email_date, then displays up to email_display_limit emails.
    """
    from .models import Configuration

    # Fetch new emails from IMAP server (incremental since latest_email_date)
    service = EmailService()
    try:
        stats = service.fetch_emails_by_date_range(days_back=30)
    except Exception as e:
        stats = {'new': 0, 'existing': 0, 'errors': [str(e)]}

    # Get display limit from configuration
    try:
        config = Configuration.objects.get(key='email_display_limit')
        display_limit = int(config.value)
    except (Configuration.DoesNotExist, ValueError):
        display_limit = 30

    # Get TempEmail records ordered by most recent first, limited to display_limit
    emails = TempEmail.objects.select_related('email_record__job').order_by('-date_sent')[:display_limit]

    context = {
        'emails': emails,
        'total_count': TempEmail.objects.count(),
        'displayed_count': emails.count(),
        'display_limit': display_limit,
        'stats': stats,
    }
    return render(request, 'core/email_inbox.html', context)

@login_required
@permission_required('core.can_manage_jobs', raise_exception=True)
def email_detail(request, email_record_id):
    """Display full email content fetched on-demand from IMAP server."""
    email_record = get_object_or_404(EmailRecord, pk=email_record_id)

    # Fetch full content from IMAP server
    service = EmailService()
    email_content = service.get_email_content(email_record_id)

    # Get temp data if available for metadata
    temp_data = None
    if hasattr(email_record, 'temp_data'):
        temp_data = email_record.temp_data

    context = {
        'email_record': email_record,
        'temp_data': temp_data,
        'email_content': email_content,
    }
    return render(request, 'core/email_detail.html', context)


@login_required
@permission_required('core.can_manage_jobs', raise_exception=True)
def create_job_from_email(request, email_record_id):
    """
    Workflow to create a job from an email.

    Steps:
    1. Parse email to extract sender info
    2. Check if Contact exists with sender's email
    3. If Contact exists: redirect to job creation with pre-filled data
    4. If Contact doesn't exist: extract company, redirect to contact creation
    """
    email_record = get_object_or_404(EmailRecord, pk=email_record_id)

    # Fetch full email content
    service = EmailService()
    email_content = service.get_email_content(email_record_id)

    if not email_content:
        messages.error(request, 'Could not fetch email content from server.')
        return redirect('core:email_detail', email_record_id=email_record_id)

    # Parse sender information
    sender_name, sender_email = parse_email_address(email_content.get('from', ''))

    if not sender_email:
        messages.error(request, 'Could not extract sender email address.')
        return redirect('core:email_detail', email_record_id=email_record_id)

    # Store email_record_id in session for later linking
    request.session['email_record_id_for_job'] = email_record_id

    # Extract email body for job description
    email_body = extract_email_body(email_content)
    request.session['email_body_for_job'] = email_body

    # Check if Contact exists with this email
    try:
        contact = Contact.objects.get(email=sender_email)
        # Contact exists - redirect to job creation with contact pre-filled
        messages.info(request, f'Found existing contact: {contact.name}')

        # Build URL with query params
        url = reverse('jobs:create') + f'?contact_id={contact.contact_id}&description={email_body[:200]}'
        return redirect(url)

    except Contact.DoesNotExist:
        # Contact doesn't exist - need to create contact first
        messages.info(request, f'No contact found for {sender_email}. Please create contact first.')

        # Try to extract company name from signature
        email_text = email_content.get('text', '')
        company_name = extract_company_from_signature(email_text)

        # Store contact data in session
        request.session['contact_name'] = sender_name
        request.session['contact_email'] = sender_email
        request.session['contact_company'] = company_name

        # Check if business exists
        suggested_business = None
        if company_name:
            # Try to find matching business (case-insensitive)
            businesses = Business.objects.filter(business_name__iexact=company_name)
            if businesses.exists():
                suggested_business = businesses.first()
                request.session['suggested_business_id'] = suggested_business.business_id
                messages.info(request, f'Found matching business: {suggested_business.business_name}')

        # Redirect to contact creation
        return redirect('contacts:add_contact')

    except Contact.MultipleObjectsReturned:
        # Multiple contacts with same email - let user choose
        contacts = Contact.objects.filter(email=sender_email)
        messages.warning(request, f'Multiple contacts found with email {sender_email}. Please select one.')
        # For now, just use the first one
        contact = contacts.first()
        url = reverse('jobs:create') + f'?contact_id={contact.contact_id}&description={email_body[:200]}'
        return redirect(url)


@login_required
@permission_required('core.can_manage_jobs', raise_exception=True)
def associate_email_with_job(request, email_record_id):
    """
    Associate an email with an existing job.

    GET: Display form with job selection dropdown
    POST: Link the email to the selected job
    """
    email_record = get_object_or_404(EmailRecord, pk=email_record_id)

    if request.method == 'POST':
        job_id = request.POST.get('job_id')

        if not job_id:
            messages.error(request, 'Please select a job.')
            return redirect('core:associate_email_with_job', email_record_id=email_record_id)

        try:
            updated = EmailService.associate_with_job(email_record_id, int(job_id))
            messages.success(request, f'Email associated with job {updated.job.job_number}.')
            return redirect('core:email_detail', email_record_id=email_record_id)
        except NotFoundError:
            messages.error(request, 'Selected job does not exist.')
            return redirect('core:associate_email_with_job', email_record_id=email_record_id)

    # GET request - show form
    # Get all jobs ordered by most recent first
    jobs = Job.objects.all().order_by('-created_date')

    # Fetch email content for display
    service = EmailService()
    email_content = service.get_email_content(email_record_id)

    # Get temp data if available for metadata
    temp_data = None
    if hasattr(email_record, 'temp_data'):
        temp_data = email_record.temp_data

    context = {
        'email_record': email_record,
        'temp_data': temp_data,
        'email_content': email_content,
        'jobs': jobs,
    }
    return render(request, 'core/associate_email_with_job.html', context)


@login_required
@permission_required('core.can_manage_jobs', raise_exception=True)
def disassociate_email_from_job(request, email_record_id):
    """
    Remove the job association from an email.

    POST only: Unlink the email from its associated job
    """
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('core:email_detail', email_record_id=email_record_id)

    email_record = get_object_or_404(EmailRecord, pk=email_record_id)

    if not email_record.job:
        messages.warning(request, 'Email is not associated with any job.')
        return redirect('core:email_detail', email_record_id=email_record_id)

    job_number = email_record.job.job_number
    EmailService.disassociate_from_job(email_record_id)

    messages.success(request, f'Email disassociated from job {job_number}.')
    return redirect('core:email_detail', email_record_id=email_record_id)

@login_required
@permission_required('core.can_manage_config', raise_exception=True)
def accounting_category_list(request):
    """List all accounting categories."""
    show_all = request.GET.get('show_all', '0') == '1'

    if show_all:
        categories = AccountingCategory.objects.all()
    else:
        categories = AccountingCategory.objects.filter(is_active=True)

    return render(request, 'core/accounting_category_list.html', {
        'accounting_categories': categories,
        'show_all': show_all,
    })


@login_required
@permission_required('core.can_manage_config', raise_exception=True)
def accounting_category_detail(request, pk):
    """Display accounting category details."""
    category = get_object_or_404(AccountingCategory, pk=pk)
    return render(request, 'core/accounting_category_detail.html', {
        'accounting_category': category,
    })


@login_required
@permission_required('core.can_manage_config', raise_exception=True)
def accounting_category_create(request):
    """Create a new accounting category."""
    if request.method == 'POST':
        form = AccountingCategoryForm(request.POST)
        if form.is_valid():
            category = ConfigurationService.create_accounting_category(**form.cleaned_data)
            messages.success(request, f'Accounting category "{category.name}" created successfully.')
            return redirect('core:accounting_category_list')
    else:
        form = AccountingCategoryForm()

    return render(request, 'core/accounting_category_form.html', {
        'form': form,
        'title': 'Create Accounting Category',
        'submit_label': 'Create',
    })


@login_required
@permission_required('core.can_manage_config', raise_exception=True)
def accounting_category_edit(request, pk):
    """Edit an existing accounting category."""
    category = get_object_or_404(AccountingCategory, pk=pk)

    if request.method == 'POST':
        form = AccountingCategoryForm(request.POST, instance=category)
        if form.is_valid():
            ConfigurationService.update_accounting_category(pk, **form.cleaned_data)
            messages.success(request, f'Accounting category "{category.name}" updated successfully.')
            return redirect('core:accounting_category_detail', pk=category.pk)
    else:
        form = AccountingCategoryForm(instance=category)

    return render(request, 'core/accounting_category_form.html', {
        'form': form,
        'accounting_category': category,
        'title': f'Edit Accounting Category: {category.name}',
        'submit_label': 'Save Changes',
    })




@login_required
@permission_required('core.can_manage_config', raise_exception=True)
def settings_view(request):
    """Display the settings page with tax configuration."""
    # Get tax configuration values
    try:
        default_tax_rate = Configuration.objects.get(key='default_tax_rate')
    except Configuration.DoesNotExist:
        default_tax_rate = None

    try:
        org_tax_multiplier = Configuration.objects.get(key='org_tax_multiplier')
    except Configuration.DoesNotExist:
        org_tax_multiplier = None

    return render(request, 'settings.html', {
        'default_tax_rate': default_tax_rate,
        'org_tax_multiplier': org_tax_multiplier,
    })


@login_required
@permission_required('core.can_manage_config', raise_exception=True)
def tax_config_edit(request):
    """Edit tax configuration settings."""
    # Get current values
    try:
        tax_rate_config = Configuration.objects.get(key='default_tax_rate')
        tax_rate_value = tax_rate_config.value
    except Configuration.DoesNotExist:
        tax_rate_value = ''

    try:
        multiplier_config = Configuration.objects.get(key='org_tax_multiplier')
        multiplier_value = multiplier_config.value
    except Configuration.DoesNotExist:
        multiplier_value = ''

    if request.method == 'POST':
        form = TaxConfigurationForm(request.POST)
        if form.is_valid():
            ConfigurationService.update_tax_config(
                default_tax_rate=form.cleaned_data.get('default_tax_rate'),
                org_tax_multiplier=form.cleaned_data.get('org_tax_multiplier'),
            )

            messages.success(request, 'Tax configuration updated successfully.')
            return redirect('settings')
    else:
        initial_data = {}
        if tax_rate_value:
            initial_data['default_tax_rate'] = tax_rate_value
        if multiplier_value:
            initial_data['org_tax_multiplier'] = multiplier_value
        form = TaxConfigurationForm(initial=initial_data)

    return render(request, 'core/tax_config_form.html', {
        'form': form,
    })
