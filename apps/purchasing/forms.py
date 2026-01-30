from django import forms
from django.core.exceptions import ValidationError
from .models import PurchaseOrder, Bill
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job
from apps.invoicing.models import PriceListItem
from apps.core.services import NumberGenerationService


class PurchaseOrderForm(forms.ModelForm):
    """Form for creating/editing PurchaseOrder"""
    business = forms.ModelChoiceField(
        queryset=Business.objects.all(),
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'}),
        empty_label="-- Select Business --"
    )
    contact = forms.ModelChoiceField(
        queryset=Contact.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        empty_label="-- Select Contact (optional) --",
        help_text='If selected, Business will be auto-assigned from Contact'
    )
    job = forms.ModelChoiceField(
        queryset=Job.objects.filter(status='approved'),
        required=False,
        empty_label="-- Select Job (optional) --"
    )
    requested_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        help_text='Optional delivery/completion date requested by buyer'
    )

    class Meta:
        model = PurchaseOrder
        fields = ['business', 'contact', 'job', 'requested_date']

    def __init__(self, *args, **kwargs):
        job = kwargs.pop('job', None)
        super().__init__(*args, **kwargs)

        # Job is optional, but if provided, pre-select it
        self.fields['job'].required = False
        if job:
            self.fields['job'].initial = job

    def clean(self):
        """Validate that if contact is provided, it must have a business."""
        cleaned_data = super().clean()
        contact = cleaned_data.get('contact')

        if contact and not contact.business:
            raise forms.ValidationError(
                f'Contact "{contact}" does not have a Business associated. '
                'Please assign a Business to this Contact before using it in a Purchase Order.'
            )

        return cleaned_data

    def save(self, commit=True):
        """Override save to generate PO number using NumberGenerationService"""
        instance = super().save(commit=False)

        # Only generate PO number for new instances (not when editing)
        if not instance.pk:
            instance.po_number = NumberGenerationService.generate_next_number('po')

        if commit:
            instance.save()
        return instance


class PurchaseOrderLineItemForm(forms.Form):
    """Form for creating a PO line item from a Price List Item"""
    price_list_item = forms.ModelChoiceField(
        queryset=PriceListItem.objects.all(),
        required=True,
        label="Price List Item"
    )
    qty = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        initial=1.0,
        widget=forms.NumberInput(attrs={'step': '0.01'}),
        label="Quantity"
    )


class BillLineItemForm(forms.Form):
    """Form for creating a Bill line item - either from Price List or manual entry"""
    # Option to select from price list OR enter manually
    price_list_item = forms.ModelChoiceField(
        queryset=PriceListItem.objects.all(),
        required=False,
        label="Price List Item (optional)",
        help_text="Select a price list item or enter details manually below"
    )

    # Manual entry fields
    description = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={'rows': 2, 'cols': 40}),
        label="Description",
        help_text="Required if not using price list item"
    )
    qty = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        initial=1.0,
        widget=forms.NumberInput(attrs={'step': '0.01'}),
        label="Quantity"
    )
    units = forms.CharField(
        max_length=50,
        required=False,
        label="Units",
        help_text="e.g., ea, hr, kg"
    )
    price = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        initial=0.00,
        widget=forms.NumberInput(attrs={'step': '0.01'}),
        label="Unit Price",
        help_text="Price per unit (required if not using price list item)"
    )

    def clean(self):
        """Validate that either price_list_item is selected OR manual fields are filled"""
        cleaned_data = super().clean()
        price_list_item = cleaned_data.get('price_list_item')
        description = cleaned_data.get('description')
        price = cleaned_data.get('price')

        # If no price list item, description and price are required
        if not price_list_item:
            if not description:
                raise forms.ValidationError(
                    'Either select a Price List Item or provide a Description for manual entry'
                )
            if price is None:
                raise forms.ValidationError(
                    'Price is required when entering a line item manually'
                )

        return cleaned_data


class PurchaseOrderStatusForm(forms.Form):
    """Form for changing PurchaseOrder status"""
    VALID_TRANSITIONS = {
        'draft': ['issued'],
        'issued': ['partly_received', 'received_in_full', 'cancelled'],
        'partly_received': ['received_in_full'],
        'received_in_full': [],  # Terminal state
        'cancelled': [],  # Terminal state
    }

    status = forms.ChoiceField(choices=[], required=True)

    def __init__(self, *args, **kwargs):
        current_status = kwargs.pop('current_status', 'draft')
        super().__init__(*args, **kwargs)

        # Set valid status choices based on current status
        valid_statuses = self.VALID_TRANSITIONS.get(current_status, [])
        # Convert status codes to display names
        from .models import PO_STATUS_CHOICES
        status_dict = dict(PO_STATUS_CHOICES)

        choices = [(current_status, f'{status_dict.get(current_status)} (current)')]
        choices.extend([(s, status_dict.get(s)) for s in valid_statuses])

        self.fields['status'].choices = choices
        self.fields['status'].initial = current_status

    @staticmethod
    def has_valid_transitions(current_status):
        """Check if the current status has any valid transitions."""
        return len(PurchaseOrderStatusForm.VALID_TRANSITIONS.get(current_status, [])) > 0

    def clean_status(self):
        """Validate that the status transition is valid."""
        return self.cleaned_data['status']


class BillStatusForm(forms.Form):
    """Form for changing Bill status"""
    VALID_TRANSITIONS = {
        'draft': ['received'],
        'received': ['partly_paid', 'paid_in_full', 'cancelled'],
        'partly_paid': ['paid_in_full'],
        'paid_in_full': ['refunded'],
        'cancelled': [],  # Terminal state
        'refunded': [],  # Terminal state
    }

    status = forms.ChoiceField(choices=[], required=True)

    def __init__(self, *args, **kwargs):
        current_status = kwargs.pop('current_status', 'draft')
        super().__init__(*args, **kwargs)

        # Set valid status choices based on current status
        valid_statuses = self.VALID_TRANSITIONS.get(current_status, [])
        # Convert status codes to display names
        from .models import BILL_STATUS_CHOICES
        status_dict = dict(BILL_STATUS_CHOICES)

        choices = [(current_status, f'{status_dict.get(current_status)} (current)')]
        choices.extend([(s, status_dict.get(s)) for s in valid_statuses])

        self.fields['status'].choices = choices
        self.fields['status'].initial = current_status

    @staticmethod
    def has_valid_transitions(current_status):
        """Check if the current status has any valid transitions."""
        return len(BillStatusForm.VALID_TRANSITIONS.get(current_status, [])) > 0

    def clean_status(self):
        """Validate that the status transition is valid."""
        return self.cleaned_data['status']


class BillForm(forms.ModelForm):
    """Form for creating a new Bill with business or contact selection"""
    business = forms.ModelChoiceField(
        queryset=Business.objects.all(),
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'}),
        empty_label="-- Select Business --"
    )
    contact = forms.ModelChoiceField(
        queryset=Contact.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        empty_label="-- Select Contact (optional) --",
        help_text='If selected, Business will be auto-assigned from Contact'
    )
    vendor_invoice_number = forms.CharField(
        max_length=50,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text='The invoice number from the vendor'
    )
    due_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        help_text='Optional due date for payment'
    )

    class Meta:
        model = Bill
        fields = ['purchase_order', 'business', 'contact', 'vendor_invoice_number', 'due_date']

    def __init__(self, *args, **kwargs):
        purchase_order = kwargs.pop('purchase_order', None)
        super().__init__(*args, **kwargs)

        # Customize contact field display to include business name
        self.fields['contact'].label_from_instance = lambda obj: f"{obj} ({obj.business.business_name})" if obj.business else str(obj)

        # If purchase_order provided, pre-select it and copy Business/Contact
        if purchase_order:
            self.fields['purchase_order'].initial = purchase_order
            self.fields['business'].initial = purchase_order.business
            if purchase_order.contact:
                self.fields['contact'].initial = purchase_order.contact

    def clean(self):
        """Validate that if contact is provided, it must have a business."""
        cleaned_data = super().clean()
        contact = cleaned_data.get('contact')

        if contact and not contact.business:
            raise forms.ValidationError(
                f'Contact "{contact}" does not have a Business associated. '
                'Please assign a Business to this Contact before using it in a Bill.'
            )

        return cleaned_data

    def save(self, commit=True):
        """Override save to set contact from cleaned_data"""
        instance = super().save(commit=False)

        # Set the contact from cleaned_data (may have been set from business)
        instance.contact = self.cleaned_data['contact']

        if commit:
            instance.save()
        return instance
