from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import (
    WorkOrderTemplate, TaskTemplate, TaskMapping,
    EstWorksheet, Task, Estimate, EstimateLineItem, Job, BundlingRule
)
from apps.contacts.models import Contact
from apps.core.models import LineItemType
from apps.core.services import NumberGenerationService


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
        fields = ['customer_po_number', 'description', 'due_date']
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

    def save(self, commit=True):
        """Override save to generate job number using NumberGenerationService"""
        instance = super().save(commit=False)

        # Set the contact from cleaned_data (may have been set from business)
        instance.contact = self.cleaned_data['contact']

        # Generate the actual job number (increments counter)
        instance.job_number = NumberGenerationService.generate_next_number('job')

        if commit:
            instance.save()
        return instance


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


class WorkOrderTemplateForm(forms.ModelForm):
    class Meta:
        model = WorkOrderTemplate
        fields = ['template_name', 'description', 'is_active']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
        }


class TaskTemplateForm(forms.ModelForm):
    task_mapping = forms.ModelChoiceField(
        queryset=TaskMapping.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        empty_label="-- Select Task Mapping (Optional) --"
    )

    class Meta:
        model = TaskTemplate
        fields = ['template_name', 'description', 'units', 'rate', 'task_mapping', 'is_active']
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


class TaskForm(forms.ModelForm):
    """Form for creating/editing Task"""
    class Meta:
        model = Task
        fields = ['name', 'template', 'est_worksheet', 'est_qty', 'units', 'rate']
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


class ManualLineItemForm(forms.ModelForm):
    """Form for creating a manual line item (not linked to a Price List Item)"""
    class Meta:
        model = EstimateLineItem
        fields = ['description', 'qty', 'units', 'price_currency', 'line_item_type']
        widgets = {
            'qty': forms.NumberInput(attrs={'step': '0.01'}),
            'price_currency': forms.NumberInput(attrs={'step': '0.01'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            'price_currency': 'Price',
            'line_item_type': 'Type',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['line_item_type'].queryset = LineItemType.objects.filter(is_active=True)
        self.fields['line_item_type'].required = True


class PriceListLineItemForm(forms.Form):
    """Form for creating a line item from a Price List Item"""
    from apps.invoicing.models import PriceListItem

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


class EstimateForm(forms.ModelForm):
    """Form for creating/editing Estimate"""
    class Meta:
        model = Estimate
        fields = ['status']
        widgets = {
            'status': forms.Select(choices=Estimate.ESTIMATE_STATUS_CHOICES)
        }
        help_texts = {
            'status': 'Estimate number will be assigned automatically on save.',
        }

    def __init__(self, *args, **kwargs):
        job = kwargs.pop('job', None)
        super().__init__(*args, **kwargs)
        # Store job for use in save method
        self._job = job

    def save(self, commit=True):
        """Override save to generate estimate number using NumberGenerationService"""
        instance = super().save(commit=False)

        # Generate the actual estimate number (increments counter)
        instance.estimate_number = NumberGenerationService.generate_next_number('estimate')

        if commit:
            instance.save()
        return instance


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


class TaskMappingForm(forms.ModelForm):
    """Form for creating/editing TaskMappings with explanatory help text."""

    class Meta:
        model = TaskMapping
        fields = [
            'task_type_id', 'step_type', 'mapping_strategy',
            'default_product_type', 'line_item_name', 'line_item_description',
            'output_line_item_type', 'breakdown_of_task'
        ]
        help_texts = {
            'task_type_id': 'Unique identifier for this mapping (e.g., "CABINET-DOOR", "DELIVERY")',
            'step_type': 'What type of work this represents in the production process',
            'mapping_strategy': 'How tasks using this mapping appear on estimates',
            'default_product_type': 'Product type for bundling (e.g., "cabinet", "table"). Required for bundle strategies.',
            'line_item_name': 'Name shown on estimate line item when using "direct" mapping',
            'line_item_description': 'Description for the line item on estimates',
            'output_line_item_type': 'Determines taxability and categorization of generated line items',
            'breakdown_of_task': 'Internal notes about what this task involves',
        }
        widgets = {
            'line_item_description': forms.Textarea(attrs={'rows': 3}),
            'breakdown_of_task': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show active LineItemTypes
        self.fields['output_line_item_type'].queryset = LineItemType.objects.filter(is_active=True)


class BundlingRuleForm(forms.ModelForm):
    """Form for creating/editing BundlingRules with explanatory help text."""

    class Meta:
        model = BundlingRule
        fields = [
            'rule_name', 'product_type', 'work_order_template',
            'line_item_template', 'description_template', 'default_units', 'combine_instances',
            'pricing_method', 'include_materials', 'include_labor', 'include_overhead',
            'output_line_item_type', 'priority', 'is_active'
        ]
        help_texts = {
            'rule_name': 'Descriptive name for this rule (e.g., "Cabinet Bundler")',
            'product_type': 'Must match TaskMapping.default_product_type (e.g., "cabinet", "table")',
            'work_order_template': 'Optional. Required if pricing_method is "template_base"',
            'line_item_template': 'Template for line item name. Use {product_type} and {bundle_identifier} placeholders.',
            'description_template': 'Template for line item description. Use {tasks_list} for bullet list of task names.',
            'default_units': 'How to calculate quantity: "each" = qty 1, "hours" = sum of task hours',
            'combine_instances': 'If checked, shows "4x Chair" instead of 4 separate line items',
            'pricing_method': 'How to calculate the bundled line item price',
            'include_materials': 'Include material costs in bundle price calculation',
            'include_labor': 'Include labor costs in bundle price calculation',
            'include_overhead': 'Include overhead costs in bundle price calculation (usually excluded from customer-facing price)',
            'output_line_item_type': 'LineItemType for bundled line items. If set, overrides the types from component task mappings.',
            'priority': 'Lower numbers = higher priority. Used when multiple rules could apply.',
            'is_active': 'Inactive rules are not applied during estimate generation',
        }
        widgets = {
            'description_template': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import WorkOrderTemplate
        self.fields['work_order_template'].queryset = WorkOrderTemplate.objects.filter(is_active=True)
        self.fields['output_line_item_type'].queryset = LineItemType.objects.filter(is_active=True)

    def clean(self):
        """
        Validate that if TaskMappings for the same product_type have different
        output_line_item_types, an explicit output_line_item_type must be set.
        """
        cleaned_data = super().clean()
        product_type = cleaned_data.get('product_type')
        output_line_item_type = cleaned_data.get('output_line_item_type')

        if product_type and not output_line_item_type:
            # Find TaskMappings with this product_type and bundle strategy
            task_mappings = TaskMapping.objects.filter(
                default_product_type=product_type,
                mapping_strategy='bundle'
            ).exclude(output_line_item_type__isnull=True)

            # Get distinct output_line_item_types
            distinct_types = set(
                task_mappings.values_list('output_line_item_type', flat=True)
            )

            if len(distinct_types) > 1:
                raise ValidationError({
                    'output_line_item_type': (
                        f"TaskMappings for '{product_type}' have conflicting "
                        "LineItemTypes. You must specify an output_line_item_type "
                        "to override the conflicting types."
                    )
                })

        return cleaned_data


# Alias for backwards compatibility
ProductBundlingRuleForm = BundlingRuleForm