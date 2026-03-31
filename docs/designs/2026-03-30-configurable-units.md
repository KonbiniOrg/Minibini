# Configurable Units

## Summary

Replace free-text `units` CharFields with a controlled vocabulary: a JSON list of allowed unit strings stored in the `Configuration` key-value store. Model fields remain CharFields (no ForeignKeys), validated against the configured list at the form/serializer layer.

## Storage

A single `Configuration` row:

- **Key:** `units_list`
- **Value:** JSON array of strings, e.g. `["none", "hours", "ea", "sq ft", "sheets", "pcs", "lbs", "kg", "gal", "qt", "L", "bd ft", "ln ft", "ft", "yd", "m"]`

List order = display order. `"none"` is always first and cannot be removed.

Initial values come from fixture data (not migrations). The seed list is derived from the current `InventoryItemForm.UNIT_CHOICES` with `"none"` prepended.

## Model Changes

Affected fields (all `CharField(max_length=50)`):

| Model | App | Current | New |
|---|---|---|---|
| `BaseLineItem.units` (abstract) | `core` | `blank=True` | `default="none"` |
| `Task.units` | `jobs` | `blank=True` | `default="none"` |
| `TaskTemplate.units` | `estimates` | `blank=True` | `default="none"` |
| `PriceListItem.units` | `inventory` | `blank=True` | `default="none"` |

No ForeignKeys. No new tables. Fields stay as CharFields storing the unit string directly.

A migration sets `default="none"` on each field. Since this is pre-production, no data migration is needed.

## Validation

A shared validator in `apps.core` (e.g., `apps/core/validators.py` or `apps/core/units.py`):

```python
def get_allowed_units():
    """Load the units list from Configuration. Cache-friendly."""
    config = Configuration.objects.get(key='units_list')
    return json.loads(config.value)

def validate_units(value):
    """Validate that a units value is in the configured list."""
    if value not in get_allowed_units():
        raise ValidationError(f'"{value}" is not a configured unit.')
```

If the `units_list` Configuration entry does not exist (e.g., fresh install before fixtures), the validator should raise a clear error — units cannot be validated without the config. This ensures fixtures are loaded before the system is usable.

This validator is used by:

- **Django forms:** All forms with a `units` field switch from text input to a `<select>` dropdown populated from the configured list. The validator runs on form clean.
- **DRF serializers:** Serializers validate the `units` field against the configured list.
- **Services:** The hardcoded `'each'` defaults in `apps/estimates/services.py` (lines 714, 739, 764) are replaced with `'none'`.

## Forms

All forms that currently have a free-text `units` field become `<select>` dropdowns populated from the configured list:

- `InventoryItemForm` — remove `UNIT_CHOICES`, `units_select`, and `units_custom` dual-field pattern entirely. Replace with a single `<select>` from config.
- `PriceListItemForm` — text input becomes `<select>`
- `TaskTemplateForm` — text input becomes `<select>`
- `ManualLineItemForm` — text input becomes `<select>`
- `POManualLineItemForm` — text input becomes `<select>`
- `BillLineItemForm` — text input becomes `<select>`
- `TaskEditForm` — text input becomes `<select>`

## API

### Existing serializers

All serializers exposing `units` add validation against the configured list. No structural changes — they still accept/return a string.

### Units list endpoint

Expose the configured units list for the Svelte frontend to populate dropdowns:

- **Endpoint:** `GET /api/settings/units/` (under the existing settings API)
- **Response:** `["none", "hours", "ea", ...]`
- **Permission:** `IsAuthenticated`

### Units management endpoints

For the settings UI to manage the list:

- **PUT /api/settings/units/** — replace the entire list (must include `"none"` as first element)
- **Permission:** `CanManageConfig`

## Frontend (Svelte)

Anywhere the frontend currently displays or accepts units as free text, switch to a `<select>` dropdown. Fetch the allowed list from `GET /api/settings/units/` on mount (or from a shared store).

Currently units appear in:
- `JobDetail.svelte` — display only (no change needed for display)
- `InvoiceDetail.svelte` — display only (no change needed for display)

Any future Svelte forms that accept units input will use the dropdown pattern.

## Settings UI

Add a units management section to the settings page (alongside other config). Allows users with `can_manage_config` to:

- View the current units list
- Add new units
- Remove units (except `"none"`)
- Reorder units (drag or move up/down)

Saves via `PUT /api/settings/units/`.

Note displayed in the UI: removing a unit does not update existing records that use it — they keep their current value, but the unit won't be available for selection going forward unless re-added. Validation only applies to new input, not existing data.

## Templates (Django HTML)

Templates that display units (read-only) need no changes — they still render the string value. Templates with forms get the `<select>` dropdown as described in the Forms section.

## Fixtures

Update all fixture files to:

1. Add a `Configuration` entry for `units_list` with the seed data
2. Ensure all `units` values in fixture data use values from the seed list
3. Replace any blank/empty `units` values with `"none"`

## Test Impact

- Tests creating objects with `units` must use values from the configured list
- Test base classes (`BaseTestCase`, `FixtureTestCase`) need the `units_list` Configuration entry in setUp or fixtures
- Existing hardcoded unit strings in tests (`'hours'`, `'sqft'`, `'square_feet'`, etc.) must be updated to match the configured list values

## What This Does NOT Change

- No new database tables
- No ForeignKey relationships
- No joins at query time
- Display-only templates untouched
- CharField storage on models unchanged (just validated now)
