from django import forms
from apps.estimates.models import (
    WorkOrderTemplate, TaskTemplate,
    EstWorksheet, EstimateLineItem
)
from apps.core.models import AccountingCategory


class WorkOrderTemplateForm(forms.ModelForm):
    class Meta:
        model = WorkOrderTemplate
        fields = ['template_name', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
        }


class TaskTemplateForm(forms.ModelForm):
    class Meta:
        model = TaskTemplate
        fields = ['template_name', 'description', 'units', 'rate', 'accounting_category']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'units': forms.TextInput(attrs={'placeholder': 'e.g., hours, pieces'}),
            'rate': forms.NumberInput(attrs={'step': '0.01', 'placeholder': '0.00'}),
        }


class EstWorksheetForm(forms.ModelForm):
    """Form for creating/editing EstWorksheet"""
    class Meta:
        model = EstWorksheet
        fields = ['job', 'template']  # Removed 'status' - always starts as draft
        widgets = {
            'template': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Template is optional
        self.fields['template'].required = False
        self.fields['template'].empty_label = "-- No Template (Manual) --"


class ManualLineItemForm(forms.ModelForm):
    """Form for creating a manual line item (not linked to a Price List Item)"""
    class Meta:
        model = EstimateLineItem
        fields = ['description', 'qty', 'units', 'price', 'accounting_category']
        widgets = {
            'qty': forms.NumberInput(attrs={'step': '0.01'}),
            'price': forms.NumberInput(attrs={'step': '0.01'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            'price': 'Price',
            'accounting_category': 'Type',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['accounting_category'].queryset = AccountingCategory.objects.filter(is_active=True)
        self.fields['accounting_category'].required = True


class PriceListLineItemForm(forms.Form):
    """Form for creating a line item from a Price List Item"""
    from apps.inventory.models import PriceListItem

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
        label="Qty"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.inventory.models import PriceListItem
        self.fields['price_list_item'].queryset = PriceListItem.objects.filter(is_active=True)



class EstimateStatusForm(forms.Form):
    """Form for changing Estimate status"""
    VALID_TRANSITIONS = {
        'draft': ['open', 'rejected'],
        'open': ['accepted', 'superseded', 'rejected', 'expired'],
        'accepted': [],  # Terminal state
        'rejected': [],  # Terminal state
        'expired': [],  # Terminal state
        'superseded': []  # Terminal state
    }

    status = forms.ChoiceField(choices=[], required=True)

    def __init__(self, *args, **kwargs):
        current_status = kwargs.pop('current_status', 'draft')
        super().__init__(*args, **kwargs)

        # Set valid status choices based on current status
        valid_statuses = self.VALID_TRANSITIONS.get(current_status, [])
        choices = [(current_status, f'{current_status.title()} (current)')]
        choices.extend([(s, s.title()) for s in valid_statuses])

        self.fields['status'].choices = choices
        self.fields['status'].initial = current_status

    @staticmethod
    def has_valid_transitions(current_status):
        """Check if the current status has any valid transitions."""
        return len(EstimateStatusForm.VALID_TRANSITIONS.get(current_status, [])) > 0

    def clean_status(self):
        status = self.cleaned_data['status']
        # Additional validation if needed
        return status
