from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Task, Job
from apps.estimates.models import TaskTemplate
from apps.inventory.models import Material
from apps.contacts.models import Contact


class JobCreateForm(forms.ModelForm):
    """Form for creating a new Job"""

    contact = forms.ModelChoiceField(
        queryset=Contact.objects.all().select_related('business'),
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'}),
        empty_label="-- Select Contact --"
    )

    due_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        })
    )

    class Meta:
        model = Job
        fields = ['name', 'customer_po_number', 'description', 'due_date']
        widgets = {
            'customer_po_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }
        help_texts = {
            'description': 'Job number will be assigned automatically on save.',
        }

    def __init__(self, *args, **kwargs):
        initial_contact = kwargs.pop('initial_contact', None)
        super().__init__(*args, **kwargs)

        # Customize contact field display to include business name
        self.fields['contact'].label_from_instance = self.label_from_instance_with_business

        # Pre-select contact if provided
        if initial_contact:
            self.fields['contact'].initial = initial_contact

    def label_from_instance_with_business(self, contact):
        """Custom label for contact dropdown to include business name"""
        if contact.business:
            return f"{contact} ({contact.business.business_name})"
        return str(contact)



class JobEditForm(forms.ModelForm):
    """
    Form for editing an existing Job with state-based field restrictions.

    Field editability by status:
    - Draft: All fields except job_number and completed_date
    - Submitted/Approved: status, name, description, due_date, customer_po_number
      (NOT contact, NOT created_date)
    - Rejected: status only (terminal state, but form allows status field)
    - Completed: All fields disabled (terminal state)
    - Cancelled: All fields disabled (terminal state)
    """
    contact = forms.ModelChoiceField(
        queryset=Contact.objects.all().select_related('business'),
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'}),
        empty_label="-- Select Contact --"
    )
    created_date = forms.DateTimeField(
        required=True,
        widget=forms.DateTimeInput(attrs={
            'type': 'datetime-local',
            'class': 'form-control'
        })
    )
    due_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        })
    )
    status = forms.ChoiceField(
        choices=Job.JOB_STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    class Meta:
        model = Job
        fields = ['contact', 'status', 'created_date', 'name', 'description', 'due_date', 'customer_po_number']
        widgets = {
            'customer_po_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Customize contact field display to include business name
        self.fields['contact'].label_from_instance = self.label_from_instance_with_business

        # Get current job status from instance
        if self.instance and self.instance.pk:
            current_status = self.instance.status

            # Apply field restrictions based on status
            if current_status == 'draft':
                # Draft: Can edit everything except job_number and completed_date
                pass  # All fields already available

            elif current_status in ['submitted', 'approved']:
                # Can't change contact or created_date
                self.fields['contact'].disabled = True
                self.fields['contact'].help_text = 'Contact cannot be changed in this status'
                self.fields['created_date'].disabled = True
                self.fields['created_date'].help_text = 'Created date cannot be changed in this status'

            elif current_status == 'rejected':
                # Can only change status (but rejected is terminal, so this shouldn't work)
                self.fields['contact'].disabled = True
                self.fields['created_date'].disabled = True
                self.fields['name'].disabled = True
                self.fields['description'].disabled = True
                self.fields['due_date'].disabled = True
                self.fields['customer_po_number'].disabled = True
                self.fields['contact'].help_text = 'Only status can be changed for rejected jobs'

            elif current_status in ['completed', 'cancelled']:
                # Terminal states: All fields disabled
                for field_name in self.fields:
                    self.fields[field_name].disabled = True

    def label_from_instance_with_business(self, contact):
        """Custom label for contact dropdown to include business name"""
        if contact.business:
            return f"{contact} ({contact.business.business_name})"
        return str(contact)


class TaskEditForm(forms.ModelForm):
    """Form for editing an existing Task's details."""
    class Meta:
        model = Task
        fields = ['name', 'description', 'units', 'rate', 'est_qty', 'line_item_type']
        widgets = {
            'est_qty': forms.NumberInput(attrs={'step': '0.01'}),
            'rate': forms.NumberInput(attrs={'step': '0.01'}),
        }


class TaskFromTemplateForm(forms.Form):
    """Form for adding Task from TaskTemplate"""
    template = forms.ModelChoiceField(
        queryset=TaskTemplate.objects.filter(is_active=True),
        required=True,
        label="Task Template"
    )
    est_qty = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        initial=1.0,
        widget=forms.NumberInput(attrs={'step': '0.01'})
    )


class WorkOrderStatusForm(forms.Form):
    """Form for changing WorkOrder status"""
    VALID_TRANSITIONS = {
        'draft': ['incomplete', 'blocked'],
        'incomplete': ['blocked', 'complete'],
        'blocked': ['incomplete', 'complete'],
        'complete': []
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

    def clean_status(self):
        status = self.cleaned_data['status']
        # Additional validation if needed
        return status


class MaterialForm(forms.ModelForm):
    """Form for adding/editing a Material on a Task."""
    description = forms.CharField(max_length=255, required=False)

    class Meta:
        model = Material
        fields = ['price_list_item', 'description', 'quantity', 'unit_cost', 'sell_price', 'line_item_type']
        widgets = {
            'quantity': forms.NumberInput(attrs={'step': '0.01'}),
            'unit_cost': forms.NumberInput(attrs={'step': '0.01'}),
            'sell_price': forms.NumberInput(attrs={'step': '0.01'}),
        }
