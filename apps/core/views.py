from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from .models import User, LineItemType, Configuration
from .forms import LineItemTypeForm, TaxConfigurationForm


def user_list(request):
    users = User.objects.all().order_by('username')
    return render(request, 'core/user_list.html', {'users': users})


def user_detail(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    return render(request, 'core/user_detail.html', {'user': user})


def line_item_type_list(request):
    """List all line item types."""
    show_all = request.GET.get('show_all', '0') == '1'

    if show_all:
        line_item_types = LineItemType.objects.all()
    else:
        line_item_types = LineItemType.objects.filter(is_active=True)

    return render(request, 'core/line_item_type_list.html', {
        'line_item_types': line_item_types,
        'show_all': show_all,
    })


def line_item_type_detail(request, pk):
    """Display line item type details."""
    line_item_type = get_object_or_404(LineItemType, pk=pk)
    return render(request, 'core/line_item_type_detail.html', {
        'line_item_type': line_item_type,
    })


def line_item_type_create(request):
    """Create a new line item type."""
    if request.method == 'POST':
        form = LineItemTypeForm(request.POST)
        if form.is_valid():
            line_item_type = form.save()
            messages.success(request, f'Line item type "{line_item_type.name}" created successfully.')
            return redirect('core:line_item_type_list')
    else:
        form = LineItemTypeForm()

    return render(request, 'core/line_item_type_form.html', {
        'form': form,
        'title': 'Create Line Item Type',
        'submit_label': 'Create',
    })


def line_item_type_edit(request, pk):
    """Edit an existing line item type."""
    line_item_type = get_object_or_404(LineItemType, pk=pk)

    if request.method == 'POST':
        form = LineItemTypeForm(request.POST, instance=line_item_type)
        if form.is_valid():
            form.save()
            messages.success(request, f'Line item type "{line_item_type.name}" updated successfully.')
            return redirect('core:line_item_type_detail', pk=line_item_type.pk)
    else:
        form = LineItemTypeForm(instance=line_item_type)

    return render(request, 'core/line_item_type_form.html', {
        'form': form,
        'line_item_type': line_item_type,
        'title': f'Edit Line Item Type: {line_item_type.name}',
        'submit_label': 'Save Changes',
    })


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
            # Update or create default_tax_rate
            tax_rate = form.cleaned_data.get('default_tax_rate')
            if tax_rate is not None:
                Configuration.objects.update_or_create(
                    key='default_tax_rate',
                    defaults={'value': str(tax_rate)}
                )

            # Update or create org_tax_multiplier
            multiplier = form.cleaned_data.get('org_tax_multiplier')
            if multiplier is not None:
                Configuration.objects.update_or_create(
                    key='org_tax_multiplier',
                    defaults={'value': str(multiplier)}
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