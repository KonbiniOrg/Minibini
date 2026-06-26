# apps/jobs/flat_fee_reframe.py
#
# HISTORICAL MIGRATION HELPER — invoked by data migration
# jobs/0045_reframe_flat_fee_prices, which runs at a point in the migration
# history where the atom FK field on Task/PlanTask/TaskTemplate is named
# `service_price` (the later jobs/0047 rename to `service_item` has NOT happened
# yet at 0045's point). That's why the FK field name is a PARAMETER (`fk_field`)
# defaulting to `service_price`: the migration uses the default; only current-
# model callers (the unit test) pass `service_item`.
#
# DO NOT hardcode/sweep this to `service_item` — a blanket rename once did, and
# it broke `migrate` on a fresh database (FieldError: the historical model has
# no `service_item`).
from decimal import Decimal

FLAT_FEE = 'flat_fee'


def _price_of(active_modifiers):
    if isinstance(active_modifiers, dict):
        raw = active_modifiers.get('flat_fee_price')
        if raw not in (None, ''):
            return Decimal(str(raw))
    return None


def reframe_flat_fee_prices(ServicePrice, Task, PlanTask, TaskTemplate, *,
                            fk_field='service_price', log=print):
    """Best-effort: relocate per-atom flat_fee_price onto dedicated ServicePrice rows.

    `fk_field` is the atom→service FK field name. It defaults to `service_price`,
    the name at migration jobs/0045's point in history (the migration calls this
    with the default); current-model callers pass `service_item`. Uses the
    literal 'flat_fee', never model constants. Returns a worklist of
    (model_name, pk, reason) for rows that couldn't be resolved.
    """
    worklist = []
    minted = {}  # (orig_service_id, price_str) -> ServicePrice

    def mint(orig, price):
        key = (orig.pk, str(price))
        if key in minted:
            return minted[key]
        name = f'{orig.name} — {price}'
        try:
            new = ServicePrice.objects.create(
                name=name, description=orig.description, algorithm=FLAT_FEE,
                rate=price, unit_label=orig.unit_label, modifiers=[],
                accounting_category=orig.accounting_category,
            )
        except Exception:  # unique-name collision or similar — log, skip
            return None
        minted[key] = new
        return new

    for model, attr in ((Task, 'active_modifiers'),
                        (PlanTask, 'active_modifiers'),
                        (TaskTemplate, 'default_active_modifiers')):
        for obj in model.objects.select_related(fk_field).all():
            svc = getattr(obj, fk_field)
            if not svc or svc.algorithm != FLAT_FEE:
                continue
            am = getattr(obj, attr)
            price = _price_of(am)
            if price is None or price <= 0:
                if isinstance(am, dict):
                    worklist.append((model.__name__, obj.pk, 'no/zero flat_fee_price'))
                continue
            new_svc = mint(svc, price)
            if new_svc is None:
                worklist.append((model.__name__, obj.pk, 'could not mint service'))
                continue
            setattr(obj, fk_field, new_svc)
            setattr(obj, attr, [])
            obj.save()
    return worklist
