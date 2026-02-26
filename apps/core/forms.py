from django import forms
from .models import LineItemType, Configuration


class TaxConfigurationForm(forms.Form):
    """Form for editing tax configuration settings."""
    default_tax_rate = forms.DecimalField(
        max_digits=5,
        decimal_places=4,
        required=False,
        help_text='Default tax rate (e.g., 0.0825 for 8.25%)'
    )
    org_tax_multiplier = forms.DecimalField(
        max_digits=5,
        decimal_places=4,
        required=False,
        help_text='Organization tax multiplier (0.00 = exempt, 1.00 = full rate)'
    )


class LineItemTypeForm(forms.ModelForm):
    """Form for creating and editing LineItemTypes."""

    class Meta:
        model = LineItemType
        fields = ['code', 'name', 'taxable', 'default_description', 'is_active']
        widgets = {
            'code': forms.TextInput(attrs={'maxlength': 20}),
            'name': forms.TextInput(attrs={'maxlength': 100}),
            'default_description': forms.Textarea(attrs={'rows': 3}),
        }
