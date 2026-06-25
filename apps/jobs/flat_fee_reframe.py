# apps/jobs/flat_fee_reframe.py
from decimal import Decimal

FLAT_FEE = 'flat_fee'


def _price_of(active_modifiers):
    if isinstance(active_modifiers, dict):
        raw = active_modifiers.get('flat_fee_price')
        if raw not in (None, ''):
            return Decimal(str(raw))
    return None


def reframe_flat_fee_prices(ServiceItem, Task, PlanTask, TaskTemplate, *, log=print):
    """Best-effort: relocate per-atom flat_fee_price onto dedicated ServiceItem rows.

    Works with both real and historical (migration) model classes — uses the
    literal 'flat_fee', never model constants. Returns a worklist of
    (model_name, pk, reason) for rows that couldn't be resolved.
    """
    worklist = []
    minted = {}  # (orig_service_id, price_str) -> ServiceItem

    def mint(orig, price):
        key = (orig.pk, str(price))
        if key in minted:
            return minted[key]
        name = f'{orig.name} — {price}'
        try:
            new = ServiceItem.objects.create(
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
        for obj in model.objects.select_related('service_item').all():
            svc = obj.service_item
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
            obj.service_item = new_svc
            setattr(obj, attr, [])
            obj.save()
    return worklist
