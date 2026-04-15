from django import forms
from apps.inventory.models import PriceListItem
from apps.core.models import AccountingCategory
from apps.core.units import UnitsFieldMixin


class InventoryItemForm(UnitsFieldMixin, forms.ModelForm):
    """Form for adding and editing inventoried price list items."""

    class Meta:
        model = PriceListItem
        fields = [
            'code',
            'units',
            'description',
            'qty_on_hand',
            'purchase_price',
            'selling_price',
            'accounting_category',
        ]

    def clean_code(self):
        code = self.cleaned_data['code']
        existing_query = PriceListItem.objects.filter(code=code, is_inventoried=True)
        if self.instance.pk:
            existing_query = existing_query.exclude(pk=self.instance.pk)
        if existing_query.exists():
            raise forms.ValidationError(f'Inventoried item with code "{code}" already exists.')
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
        instance.is_inventoried = True
        if commit:
            instance.save()
        return instance


class PriceListItemForm(UnitsFieldMixin, forms.ModelForm):
    """Form for creating and editing PriceListItem."""

    class Meta:
        model = PriceListItem
        fields = [
            'code',
            'units',
            'description',
            'purchase_price',
            'selling_price',
            'is_inventoried',
            'qty_on_hand',
            'qty_sold',
            'qty_wasted',
            'accounting_category',
            'is_active',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show active AccountingCategorys in the dropdown
        self.fields['accounting_category'].queryset = AccountingCategory.objects.filter(is_active=True)
        # Only show is_active field when editing existing items (not on create)
        if self.instance.pk:
            self.fields['is_active'].label = "Active (uncheck to archive)"
        else:
            # For new items, remove the is_active field - they're always active by default
            del self.fields['is_active']

        # Hide quantity fields for non-inventoried items
        # Check both the instance (for GET) and submitted data (for POST)
        is_inventoried = self.instance.is_inventoried
        if self.data:
            is_inventoried = 'is_inventoried' in self.data
        if not is_inventoried:
            del self.fields['qty_on_hand']
            del self.fields['qty_sold']
            del self.fields['qty_wasted']


    def clean_code(self):
        """Ensure code is unique when creating a new item or updating."""
        code = self.cleaned_data['code']
        # Check for duplicates, excluding the current instance if it's an update
        existing_query = PriceListItem.objects.filter(code=code)
        if self.instance.pk:
            existing_query = existing_query.exclude(pk=self.instance.pk)

        if existing_query.exists():
            raise forms.ValidationError(f'Item with code "{code}" already exists.')
        return code

    def clean_purchase_price(self):
        """Ensure purchase price is not negative."""
        purchase_price = self.cleaned_data['purchase_price']
        if purchase_price < 0:
            raise forms.ValidationError('Purchase price cannot be negative.')
        return purchase_price

    def clean_selling_price(self):
        """Ensure selling price is not negative."""
        selling_price = self.cleaned_data['selling_price']
        if selling_price < 0:
            raise forms.ValidationError('Selling price cannot be negative.')
        return selling_price

    def clean_qty_on_hand(self):
        """Ensure quantity on hand is not negative."""
        qty_on_hand = self.cleaned_data['qty_on_hand']
        if qty_on_hand < 0:
            raise forms.ValidationError('Quantity on hand cannot be negative.')
        return qty_on_hand

    def clean_qty_sold(self):
        """Ensure quantity sold is not negative."""
        qty_sold = self.cleaned_data['qty_sold']
        if qty_sold < 0:
            raise forms.ValidationError('Quantity sold cannot be negative.')
        return qty_sold

    def clean_qty_wasted(self):
        """Ensure quantity wasted is not negative."""
        qty_wasted = self.cleaned_data['qty_wasted']
        if qty_wasted < 0:
            raise forms.ValidationError('Quantity wasted cannot be negative.')
        return qty_wasted
