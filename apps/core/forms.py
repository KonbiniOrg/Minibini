from django import forms
from .models import AccountingCategory


class AccountingCategoryForm(forms.ModelForm):
    """Form for creating and editing AccountingCategories."""

    class Meta:
        model = AccountingCategory
        fields = ['code', 'name', 'taxable', 'default_description', 'is_active']
        widgets = {
            'code': forms.TextInput(attrs={'maxlength': 20}),
            'name': forms.TextInput(attrs={'maxlength': 100}),
            'default_description': forms.Textarea(attrs={'rows': 3}),
        }
