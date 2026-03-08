from django import forms
from .models import Invoice
from apps.core.services import NumberGenerationService


class InvoiceForm(forms.ModelForm):
    """Form for creating/editing Invoice"""

    class Meta:
        model = Invoice
        fields = ['job', 'status']
        widgets = {
            'status': forms.Select(choices=Invoice.INVOICE_STATUS_CHOICES)
        }
        help_texts = {
            'job': 'Invoice number will be assigned automatically on save.',
        }

    def __init__(self, *args, **kwargs):
        job = kwargs.pop('job', None)
        super().__init__(*args, **kwargs)

        # If job is provided, pre-select it
        if job:
            self.fields['job'].initial = job

    def save(self, commit=True):
        """Override save to generate invoice number using NumberGenerationService"""
        instance = super().save(commit=False)

        # Generate the actual invoice number (increments counter)
        instance.invoice_number = NumberGenerationService.generate_next_number('invoice')

        if commit:
            instance.save()
        return instance
