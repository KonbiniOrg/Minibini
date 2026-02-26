from django import forms
from .models import InventoryItem

UNIT_CHOICES = [
    ('sq ft', 'sq ft (square feet)'),
    ('ft', 'ft (feet)'),
    ('yd', 'yd (yards)'),
    ('m', 'm (meters)'),
    ('sheets', 'sheets'),
    ('pcs', 'pcs (pieces)'),
    ('ea', 'ea (each)'),
    ('lbs', 'lbs (pounds)'),
    ('kg', 'kg (kilograms)'),
    ('gal', 'gal (gallons)'),
    ('qt', 'qt (quarts)'),
    ('L', 'L (liters)'),
    ('bd ft', 'bd ft (board feet)'),
    ('ln ft', 'ln ft (linear feet)'),
    ('other', 'Other'),
]


class InventoryItemForm(forms.ModelForm):
    """Form for adding and editing inventory items."""

    units_select = forms.ChoiceField(choices=UNIT_CHOICES, label='Units')
    units_custom = forms.CharField(required=False, label='Custom units')

    class Meta:
        model = InventoryItem
        fields = [
            'code',
            'description',
            'qty_on_hand',
            'purchase_price',
            'selling_price',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.units:
            predefined = [c[0] for c in UNIT_CHOICES if c[0] != 'other']
            if self.instance.units in predefined:
                self.fields['units_select'].initial = self.instance.units
            else:
                self.fields['units_select'].initial = 'other'
                self.fields['units_custom'].initial = self.instance.units

    def clean(self):
        cleaned_data = super().clean()
        units_select = cleaned_data.get('units_select')
        units_custom = cleaned_data.get('units_custom', '').strip()

        if units_select == 'other':
            if not units_custom:
                self.add_error('units_custom', 'Please enter a custom unit.')
        return cleaned_data

    def clean_code(self):
        code = self.cleaned_data['code']
        existing_query = InventoryItem.objects.filter(code=code)
        if self.instance.pk:
            existing_query = existing_query.exclude(pk=self.instance.pk)
        if existing_query.exists():
            raise forms.ValidationError(f'Item with code "{code}" already exists.')
        return code

    def clean_purchase_price(self):
        purchase_price = self.cleaned_data['purchase_price']
        if purchase_price < 0:
            raise forms.ValidationError('Purchase price cannot be negative.')
        return purchase_price

    def clean_selling_price(self):
        selling_price = self.cleaned_data['selling_price']
        if selling_price < 0:
            raise forms.ValidationError('Selling price cannot be negative.')
        return selling_price

    def clean_qty_on_hand(self):
        qty_on_hand = self.cleaned_data['qty_on_hand']
        if qty_on_hand < 0:
            raise forms.ValidationError('Quantity on hand cannot be negative.')
        return qty_on_hand

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data['units_select'] == 'other':
            instance.units = self.cleaned_data['units_custom'].strip()
        else:
            instance.units = self.cleaned_data['units_select']
        if commit:
            instance.save()
        return instance
