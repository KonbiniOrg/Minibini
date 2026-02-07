# Line Item Type and Taxability Design

## Overview

This document describes the design for adding taxability support to Minibini through a new `LineItemType` model. The goal is to:

1. Categorize line items by type (Service, Material, Product, etc.)
2. Support per-type default taxability
3. Allow line-item-level overrides for taxability and rate
4. Handle customer tax exemptions (full or partial)
5. Apply symmetrically to both sales (Estimate/Invoice) and purchases (PO/Bill)

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Tax rate model | Single rate (app default) | Sufficient for current needs; composite rates can be added later |
| Taxability location | Type default + line item override | Handles common case simply, allows exceptions |
| Line item override scope | Taxability AND rate | Flexibility for edge cases (special tax treatment) |
| Customer exemption model | Multiplier (0.0 - 1.0) | Handles full exemption (0), partial (0.5), and full rate (1.0/null) without storing absolute rates |
| LineItemType FK location | BaseLineItem (required) | Consistent across all line item types; taxability applies to both sales and purchases |
| Taxability flags | Single `taxable` field | Exemption is buyer-side, not item-side; same flag works for sales and purchases |

## Data Model Changes

### New Model: LineItemType

```python
class LineItemType(models.Model):
    """
    Defines categories of line items with default taxability.
    Examples: Service, Material, Product, Freight, Overhead
    """
    code = models.CharField(max_length=20, unique=True)  # e.g., "SVC", "MAT", "PRD"
    name = models.CharField(max_length=100)  # e.g., "Service", "Material", "Product"
    taxable = models.BooleanField(default=True)  # Default taxability for this type
    default_units = models.CharField(max_length=50, blank=True)  # e.g., "hours", "each"
    default_description = models.TextField(blank=True)  # Template for descriptions
    is_active = models.BooleanField(default=True)  # Soft delete support

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
```

### Modified Model: BaseLineItem

Add to `apps/core/models.py`:

```python
class BaseLineItem(models.Model):
    # ... existing fields ...

    # New fields
    line_item_type = models.ForeignKey(
        'core.LineItemType',  # or wherever it lives
        on_delete=models.PROTECT,
        related_name='%(class)s_items'
    )
    taxable_override = models.BooleanField(null=True, blank=True)  # null = use type default
    tax_rate_override = models.DecimalField(
        max_digits=5,
        decimal_places=4,  # Supports rates like 0.0825 (8.25%)
        null=True,
        blank=True
    )  # null = use app default
```

### Modified Model: Business

Add to `apps/contacts/models.py`:

```python
class Business(models.Model):
    # ... existing fields ...

    # Existing field (keep)
    tax_exemption_number = models.CharField(max_length=100, blank=True)

    # New field
    tax_multiplier = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True
    )  # null/1.0 = full rate, 0 = exempt, 0.5 = half rate
```

### Modified Model: Configuration

Add app-level tax settings:

```python
# In Configuration or via new fields
default_tax_rate = models.DecimalField(
    max_digits=5,
    decimal_places=4,
    default=Decimal('0.0')
)  # e.g., 0.08 for 8%

org_tax_multiplier = models.DecimalField(
    max_digits=3,
    decimal_places=2,
    null=True,
    blank=True
)  # Our exemption status when purchasing
```

### Modified Model: TaskMapping

Add reference to LineItemType:

```python
class TaskMapping(models.Model):
    # ... existing fields ...

    # New field
    output_line_item_type = models.ForeignKey(
        'core.LineItemType',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="LineItemType to assign when tasks with this mapping become line items"
    )
```

### Modified Model: PriceListItem

Add reference to LineItemType:

```python
class PriceListItem(models.Model):
    # ... existing fields ...

    # New field
    line_item_type = models.ForeignKey(
        'core.LineItemType',
        on_delete=models.PROTECT,
        related_name='price_list_items'
    )
```

## Tax Calculation Logic

### New Service: TaxCalculationService

Location: `apps/core/services.py`

```python
class TaxCalculationService:
    """Calculates tax for line items."""

    @staticmethod
    def get_effective_taxability(line_item):
        """Determine if a line item is taxable."""
        if line_item.taxable_override is not None:
            return line_item.taxable_override
        return line_item.line_item_type.taxable

    @staticmethod
    def get_effective_tax_rate(line_item):
        """Get the tax rate for a line item."""
        if line_item.tax_rate_override is not None:
            return line_item.tax_rate_override
        return Configuration.get_value('default_tax_rate', Decimal('0'))

    @staticmethod
    def calculate_line_item_tax(line_item, customer=None):
        """
        Calculate tax amount for a single line item.

        Args:
            line_item: The line item to calculate tax for
            customer: Business object (for customer multiplier) or None for purchases

        Returns:
            Decimal: Tax amount
        """
        if not TaxCalculationService.get_effective_taxability(line_item):
            return Decimal('0')

        rate = TaxCalculationService.get_effective_tax_rate(line_item)

        # Apply customer/org multiplier
        if customer and customer.tax_multiplier is not None:
            rate = rate * customer.tax_multiplier
        elif customer is None:
            # Purchasing - use org multiplier
            org_multiplier = Configuration.get_value('org_tax_multiplier')
            if org_multiplier is not None:
                rate = rate * org_multiplier

        return (line_item.total_amount * rate).quantize(Decimal('0.01'))

    @staticmethod
    def calculate_document_tax(document, customer=None):
        """Calculate total tax for an estimate, invoice, PO, or bill."""
        total_tax = Decimal('0')
        for line_item in document.get_line_items():
            total_tax += TaxCalculationService.calculate_line_item_tax(line_item, customer)
        return total_tax
```

## Service Changes

### EstimateGenerationService

Modify to assign `line_item_type` when creating line items from tasks:

```python
def _create_line_item(self, task, ...):
    # Get LineItemType from TaskMapping
    line_item_type = None
    if task.template and task.template.mapping:
        line_item_type = task.template.mapping.output_line_item_type

    if not line_item_type:
        # Fallback to default type
        line_item_type = LineItemType.objects.get(code='MISC')

    return EstimateLineItem.objects.create(
        estimate=estimate,
        line_item_type=line_item_type,
        # ... other fields
    )
```

### LineItemTaskService

No changes needed for tax - it copies line items to tasks, not the reverse.

## Migration Strategy

### Phase 1: Add Models and Fields

1. Create `LineItemType` model
2. Add nullable `line_item_type` FK to `BaseLineItem`
3. Add `taxable_override` and `tax_rate_override` to `BaseLineItem`
4. Add `tax_multiplier` to `Business`
5. Add `default_tax_rate` and `org_tax_multiplier` to `Configuration`

### Phase 2: Create Default Data

1. Create default LineItemTypes:
   - `SVC` - Service (taxable: False)
   - `MAT` - Material (taxable: True)
   - `PRD` - Product (taxable: True)
   - `FRT` - Freight (taxable: varies by jurisdiction, default True)
   - `MISC` - Miscellaneous (taxable: True)

2. Set `default_tax_rate` in Configuration (e.g., 0.08 for 8%)

### Phase 3: Backfill Existing Data

1. Assign LineItemType to existing line items based on heuristics:
   - If `task.template.mapping.step_type == 'labor'` → Service
   - If `task.template.mapping.step_type == 'material'` → Material
   - If `task.template.mapping.step_type == 'product'` → Product
   - Otherwise → Miscellaneous

2. Alternatively: Assign all existing to Miscellaneous, let users recategorize

### Phase 4: Make FK Required

1. After backfill verified, make `line_item_type` non-nullable

### Phase 5: Update TaskMapping and PriceListItem

1. Add `output_line_item_type` to `TaskMapping`
2. Add `line_item_type` to `PriceListItem`
3. Backfill based on existing `step_type` and item categories

## Implementation Tasks

### Models (apps/core/models.py, apps/contacts/models.py, apps/jobs/models.py)

- [ ] Create `LineItemType` model
- [ ] Add `line_item_type` FK to `BaseLineItem` (nullable initially)
- [ ] Add `taxable_override` to `BaseLineItem`
- [ ] Add `tax_rate_override` to `BaseLineItem`
- [ ] Add `tax_multiplier` to `Business`
- [ ] Add `output_line_item_type` FK to `TaskMapping`
- [ ] Add `line_item_type` FK to `PriceListItem`

### Configuration

- [ ] Add `default_tax_rate` configuration key
- [ ] Add `org_tax_multiplier` configuration key

### Services (apps/core/services.py)

- [ ] Create `TaxCalculationService` with methods:
  - `get_effective_taxability()`
  - `get_effective_tax_rate()`
  - `calculate_line_item_tax()`
  - `calculate_document_tax()`

### Service Updates

- [ ] Update `EstimateGenerationService` to assign `line_item_type`
- [ ] Update line item creation in `LineItemTaskService` (catalog and manual cases)

### Migrations

- [ ] Migration: Create `LineItemType` model
- [ ] Migration: Add new fields to `BaseLineItem`
- [ ] Migration: Add `tax_multiplier` to `Business`
- [ ] Data migration: Create default LineItemTypes
- [ ] Data migration: Backfill existing line items
- [ ] Migration: Make `line_item_type` non-nullable

### Admin

- [ ] Register `LineItemType` in admin
- [ ] Add `line_item_type` to line item admin forms
- [ ] Add `tax_multiplier` to Business admin

### Tests

- [ ] Unit tests for `TaxCalculationService`
- [ ] Test taxability inheritance (type default → line item override)
- [ ] Test rate inheritance (app default → line item override)
- [ ] Test customer multiplier (full, partial, exempt)
- [ ] Test org multiplier for purchases
- [ ] Integration tests for estimate generation with types
- [ ] Integration tests for PO/Bill tax calculation

## Known Issues to Fix

**Unrelated but discovered during exploration:**

- [ ] `WorkOrderService.create_from_estimate()` calls placeholder `TaskService.create_from_line_item()` instead of the proper `LineItemTaskService.generate_tasks_for_work_order()`

## Future Considerations

- **Composite tax rates**: When needed, add a `TaxRate` model with components (GST, PST) and replace the single `default_tax_rate` with an FK
- **Tax jurisdictions**: If rates vary by customer location, add jurisdiction lookup
- **Units model**: Replace `default_units` CharField with FK to a `Unit` model for standardization
- **International**: Different countries may have VAT, GST, or other tax models with different rules

## Open Questions

None at this time.
