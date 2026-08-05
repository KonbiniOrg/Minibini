from decimal import Decimal, InvalidOperation

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from apps.api.mixins import JobScopedCanManageMixin, InvoiceRefMixin
from apps.jobs.models import RateScheme, Task
from apps.inventory.models import Material
from apps.core.models import AccountingCategory
from apps.core.units import UnitsField


class MaterialSerializer(InvoiceRefMixin, serializers.ModelSerializer):
    invoice_source_type = 'material'
    is_expense_bound = serializers.BooleanField(read_only=True)
    po_line_item_id = serializers.SerializerMethodField()
    po_id = serializers.SerializerMethodField()
    po_number = serializers.SerializerMethodField()
    po_status = serializers.SerializerMethodField()
    qty_on_hand = serializers.SerializerMethodField()
    qty_on_order = serializers.SerializerMethodField()
    qty_available = serializers.SerializerMethodField()
    invoice = serializers.SerializerMethodField()

    class Meta:
        model = Material
        fields = [
            'material_id', 'description', 'quantity',
            'units', 'unit_cost', 'sell_price', 'inventory_item',
            'accounting_category',
            'consumption_state', 'released_qty', 'cost_source',
            'is_expense_bound',
            'po_line_item_id', 'po_id', 'po_number', 'po_status',
            'qty_on_hand', 'qty_on_order', 'qty_available',
            'invoice',
        ]
        read_only_fields = fields

    def get_po_line_item_id(self, obj):
        return obj.po_line_item_id

    def get_po_id(self, obj):
        from apps.inventory.serializer_helpers import material_po_line_item
        pol = material_po_line_item(obj)
        return pol.purchase_order_id if pol else None

    def get_po_number(self, obj):
        from apps.inventory.serializer_helpers import material_po_line_item
        pol = material_po_line_item(obj)
        return pol.purchase_order.po_number if pol else None

    def get_po_status(self, obj):
        from apps.inventory.serializer_helpers import material_po_line_item
        pol = material_po_line_item(obj)
        return pol.purchase_order.status if pol else None

    def get_qty_on_hand(self, obj):
        from apps.inventory.serializer_helpers import material_qty_on_hand
        return material_qty_on_hand(obj)

    def get_qty_on_order(self, obj):
        from apps.inventory.serializer_helpers import material_qty_on_order
        return material_qty_on_order(obj)

    def get_qty_available(self, obj):
        if obj.consumption_state == Material.CONSUMPTION_STATE_CONSUMED:
            return None
        if not obj.inventory_item_id:
            return None
        earmarked = getattr(obj, '_inv_earmarked', None)
        if earmarked is not None:
            return str(obj.inventory_item.qty_on_hand - earmarked)
        return str(obj.inventory_item.qty_available)


class MaterialWriteSerializer(serializers.ModelSerializer):
    units = UnitsField(required=False)
    propagate_to_pli = serializers.BooleanField(
        write_only=True, required=False,
    )
    accounting_category = serializers.PrimaryKeyRelatedField(
        queryset=AccountingCategory.objects.all(),
        required=False,
        allow_null=True,
    )
    customer_supplied = serializers.BooleanField(
        write_only=True, required=False, default=False,
    )

    class Meta:
        model = Material
        fields = [
            'material_id', 'description', 'quantity',
            'units', 'unit_cost', 'sell_price', 'inventory_item',
            'accounting_category', 'propagate_to_pli', 'customer_supplied',
        ]
        read_only_fields = ['material_id']

    def update(self, instance, validated_data):
        from apps.inventory.serializer_helpers import (
            enforce_pli_linked_allowlist, PLI_LINKED_PRICING_ALLOWED, FREEFORM_ALLOWED,
        )
        if instance.inventory_item_id is not None:
            enforce_pli_linked_allowlist(
                instance, validated_data, PLI_LINKED_PRICING_ALLOWED,
            )
        else:
            disallowed = set(validated_data.keys()) - FREEFORM_ALLOWED
            if disallowed:
                raise serializers.ValidationError({
                    'detail': f'Disallowed fields on freeform Material: {sorted(disallowed)}',
                })
        validated_data.pop('propagate_to_pli', None)
        return super().update(instance, validated_data)


class TaskSerializer(JobScopedCanManageMixin, InvoiceRefMixin, serializers.ModelSerializer):
    """Serializer for tasks nested under /api/jobs/{id}/tasks/.

    Task-owned money (Phase 1): the task owns its own money block
    (``qty_source``/``rate``/``unit_label``/``accounting_category``/
    ``active_modifiers``) — ``rate_scheme`` is a write-only CREATE-time
    trigger (a RateScheme preset id) that stamps those fields onto the
    task via ``Task.stamp_from_scheme``; it is never itself persisted.
    ``source_scheme`` is the resulting provenance pointer — read-only,
    never client-settable directly.

    Writing any of ``MONEY_FIELDS`` requires ``CanManageJobOrPM`` (the
    can_manage_jobs atom or the task's job's project_manager) or the
    can_manage_financials atom; everyone else gets stamp-only creation
    (``rate_scheme`` alone) and non-money edits — see ``validate()``.

    RM browser-testing note 5 (client-side restamp): ``source_scheme`` is
    now also client-settable, but UPDATE ONLY — create keeps its
    ``rate_scheme`` server-stamp contract untouched (``validate_source_scheme``
    rejects it when ``self.instance is None``). On update, the SPA's
    edit-task dropdown lets a manager/PM/financials caller re-pick which
    preset a task is stamped from; the client computes the restamp
    (rate/unit_label/accounting_category/active_modifiers, all already
    independently editable MONEY_FIELDS) from the newly-picked scheme's
    already-fetched list data and sends the whole money block in the SAME
    PATCH. The server does NOT re-derive those fields from the new
    ``source_scheme`` — it just records the provenance pointer, validated
    with the same rules as create's ``rate_scheme`` (must exist, active,
    non-percentage). A client write where the money fields don't actually
    match the new scheme's current data is not rejected — it shows up as
    drift on the task, which is the provenance pointer doing its job as an
    audit trail, not a bug for this serializer to guard against.
    """
    can_manage_job_path = 'job'
    invoice_source_type = 'task'

    # Money fields requiring CanManageJobOrPM / can_manage_financials to
    # WRITE (read is open to everyone, same as the rest of the task).
    MONEY_FIELDS = {
        'rate', 'unit_label', 'qty_source', 'accounting_category',
        'active_modifiers', 'source_scheme',
    }

    assignee_name = serializers.SerializerMethodField()
    parent_task_name = serializers.CharField(
        source='parent_task.name', read_only=True, default=None)
    actual_hours = serializers.SerializerMethodField()
    # Write-only CREATE trigger — a RateScheme preset id. Stamps qty_source/
    # rate/unit_label/accounting_category/active_modifiers/source_scheme
    # onto the task server-side (apps.api.mixins.JobTaskMixin.tasks /
    # apps.api.tasks.views.TaskViewSet.subtasks); never itself a model field.
    rate_scheme = serializers.PrimaryKeyRelatedField(
        queryset=RateScheme.objects.all(), write_only=True,
        required=False, allow_null=True,
    )
    # Nullable on the model (Phase 3 relaxes further); the API tightens to
    # required so every task gets a real AC — satisfied for stamp-only
    # creation by the view pre-filling it from the chosen preset (the same
    # value stamp_from_scheme would set) before validation runs.
    accounting_category = serializers.PrimaryKeyRelatedField(
        queryset=AccountingCategory.objects.all(), required=True,
    )
    # Provenance pointer. CREATE: set exclusively via stamp_from_scheme
    # (triggered by `rate_scheme`) — never client-settable on create, see
    # validate_source_scheme. UPDATE (RM browser-testing note 5): a
    # manager/PM/financials caller MAY set this directly, to re-pick which
    # preset the task is stamped from — the client-side restamp described
    # in the class docstring. required=False: an edit PATCH that doesn't
    # touch the scheme just omits the key, same as any other MONEY_FIELDS
    # entry.
    source_scheme = serializers.PrimaryKeyRelatedField(
        queryset=RateScheme.objects.all(), required=False,
    )
    source_scheme_name = serializers.CharField(
        source='source_scheme.name', read_only=True, default=None)
    effective_rate = serializers.SerializerMethodField()
    computed_charge = serializers.SerializerMethodField()
    has_active_blep = serializers.SerializerMethodField()
    active_worker_count = serializers.SerializerMethodField()
    has_bleps = serializers.SerializerMethodField()
    invoice = serializers.SerializerMethodField()
    claimed = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'task_id', 'name', 'description', 'sort_order', 'status',
            'blocked_reason',
            'parent_task', 'parent_task_name', 'assignee', 'assignee_name',
            'worker_queue',
            'rate_scheme',
            'qty_source', 'rate', 'unit_label', 'accounting_category',
            'active_modifiers',
            'source_scheme', 'source_scheme_name',
            'est_qty', 'est_worker_time', 'actual_qty',
            'effective_rate', 'computed_charge',
            'actual_hours',
            'has_active_blep', 'active_worker_count', 'has_bleps',
            'can_manage', 'can_edit',
            'invoice',
            'claimed',
        ]
        read_only_fields = ['task_id', 'sort_order', 'status']

    def validate_rate_scheme(self, value):
        if value and value.algorithm == RateScheme.PERCENTAGE:
            raise serializers.ValidationError(
                'Percentage services are document adjustments and cannot bill a task.'
            )
        return value

    def validate_rate(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError('Rate cannot be negative.')
        return value

    def validate_source_scheme(self, value):
        """UPDATE only (RM browser-testing note 5) — mirrors
        validate_rate_scheme's percentage rejection plus an explicit
        is_active check. Create-time's equivalent lives in
        TaskService.create_direct (SchemeInactiveError, with an
        allow_inactive_scheme escape hatch reserved for worksheet
        carry-over); there is no such escape hatch here — a restamp is
        always a deliberate pick of a CURRENTLY-offered target (the SPA's
        edit-mode dropdown only lists active, non-percentage,
        task-applicable schemes as selectable targets in the first
        place), so an inactive/percentage value here always means a
        malformed or stale client request, never a legitimate carry-over."""
        if self.instance is None:
            raise serializers.ValidationError(
                'source_scheme cannot be set on create — use rate_scheme.'
            )
        if not value.is_active:
            raise serializers.ValidationError('Selected RateScheme is inactive.')
        if value.algorithm == RateScheme.PERCENTAGE:
            raise serializers.ValidationError(
                'Percentage services are document adjustments and cannot bill a task.'
            )
        return value

    def validate_active_modifiers(self, value):
        """The contract is asymmetric by design (task-owned-money Phase 1):
        on CREATE (no instance yet) ``active_modifiers`` is a list of
        modifier KEY STRINGS — resolved into snapshot dicts server-side by
        ``Task.stamp_from_scheme``. On UPDATE (instance exists) it's the
        full ``{key, label, percent}`` snapshot list itself, applied
        directly via ``setattr`` in ``TaskService.update_task`` — there's no
        re-stamp step to resolve bare keys against. Without this check, a
        manager PATCHing key-strings (the create shape) persists a
        malformed row and ``Task.effective_rate()`` blows up on every
        later read of that task."""
        if not isinstance(value, list):
            raise serializers.ValidationError('Must be a list.')
        if self.instance is None:
            for item in value:
                if not isinstance(item, str):
                    raise serializers.ValidationError(
                        'On create, active_modifiers must be a list of '
                        'modifier key strings.'
                    )
            return value
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError(
                    'On update, active_modifiers must be a list of '
                    '{key, percent} snapshot dicts.'
                )
            key = item.get('key')
            if not isinstance(key, str) or not key:
                raise serializers.ValidationError(
                    'Each active_modifiers entry needs a string "key".'
                )
            label = item.get('label')
            if label is not None and not isinstance(label, str):
                raise serializers.ValidationError(
                    'active_modifiers "label" must be a string.'
                )
            percent = item.get('percent')
            # bool is a subclass of int (isinstance(True, int) is True), so
            # mirror validate_data's Decimal(str(...)) idiom instead of an
            # isinstance numeric check — str(True) == 'True', which Decimal
            # rejects, so bool is correctly excluded without a special case.
            try:
                Decimal(str(percent))
            except (InvalidOperation, TypeError, ValueError):
                raise serializers.ValidationError(
                    'active_modifiers "percent" must be numeric.'
                )
        return value

    def _resolve_job(self):
        """The task's job — from the instance on update, or the view-supplied
        `job` context key on create (there's no instance yet)."""
        if self.instance is not None:
            return self.instance.job
        return self.context.get('job')

    def _can_write_money(self):
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        if not user or not user.is_authenticated:
            return False
        if user.has_perm('core.can_manage_financials'):
            return True
        from apps.jobs.services import JobService
        return JobService.user_can_manage(user, self._resolve_job())

    def validate(self, attrs):
        # Gate on the RAW keys the client actually sent — not
        # `validated_data`, which the view may have pre-filled (see
        # `prefill_accounting_category`) with a value the client never
        # supplied. `raw_input_keys` (view-supplied context) reflects the
        # original request body; fall back to initial_data for callers that
        # don't provide it.
        raw_keys = self.context.get('raw_input_keys')
        if raw_keys is None:
            raw_keys = set(getattr(self, 'initial_data', {}) or {})
        money_keys = self.MONEY_FIELDS & set(raw_keys)
        if money_keys and not self._can_write_money():
            raise PermissionDenied(
                'Only a manager, the project manager, or financials may set '
                + ', '.join(sorted(money_keys)) + '.'
            )
        return attrs

    @staticmethod
    def prefill_accounting_category(data):
        """CREATE convenience: a stamp-only `rate_scheme` POST doesn't (and
        for a worker, may not) include `accounting_category` directly, but
        the field is `required=True` on this serializer. Since stamping
        (`Task.stamp_from_scheme`) is about to copy the preset's own
        accounting_category onto the task anyway, pre-fill it here so
        required-field validation sees the value it's about to get. A
        missing/invalid `rate_scheme` id is left alone — `rate_scheme`'s own
        field validation (or `accounting_category` staying absent) renders
        the real error downstream. Returns a new mapping; never mutates
        `data` in place."""
        if 'accounting_category' in data or not data.get('rate_scheme'):
            return data
        scheme = RateScheme.objects.filter(pk=data.get('rate_scheme')).first()
        if scheme is None or scheme.accounting_category_id is None:
            return data
        filled = dict(data)
        filled['accounting_category'] = scheme.accounting_category_id
        return filled

    def get_assignee_name(self, obj):
        if obj.assignee:
            name = obj.assignee.get_full_name()
            return name if name else obj.assignee.username
        return None

    def get_actual_hours(self, obj):
        from datetime import timedelta
        from decimal import Decimal
        from apps.core.timeutils import timedelta_to_hours
        total = sum(
            (b.elapsed for b in obj.blep_set.all() if b.elapsed is not None),
            timedelta(),
        )
        # float at the JSON boundary; the arithmetic is the shared Decimal path
        return float(timedelta_to_hours(total).quantize(Decimal('0.01')))

    def get_effective_rate(self, obj):
        rate = obj.effective_rate()
        return str(rate) if rate is not None else None

    def get_computed_charge(self, obj):
        try:
            return str(obj.compute_amount())
        except Exception:
            return None

    # Activity facets — derived, not stored. 'active' = an open blep exists right
    # now; 'worked' = bleps exist (any). Reuses the prefetched blep_set cache.
    def get_has_active_blep(self, obj):
        return any(b.end_time is None for b in obj.blep_set.all())

    def get_active_worker_count(self, obj):
        return len({b.user_id for b in obj.blep_set.all() if b.end_time is None})

    def get_has_bleps(self, obj):
        return len(obj.blep_set.all()) > 0

    def get_claimed(self, obj):
        """True iff a non-superseded estimate on this job has claimed this task."""
        claims = self.context.get('estimate_claims') or frozenset()
        return ('task', obj.pk) in claims

    def get_can_edit(self, obj):
        """The C1 editability matrix, precomputed for the SPA: pending is
        open to any authenticated user; in_progress/blocked to the manager
        atom, the job's PM, or the task's assignee; terminal is frozen.
        False without a request in context (nested render) — the tree
        falls back to hiding edit affordances, never showing dead ones."""
        request = self.context.get('request')
        if request is None or not getattr(request, 'user', None) \
                or not request.user.is_authenticated:
            return False
        if obj.status in (Task.STATUS_COMPLETE, Task.STATUS_CANCELLED):
            return False
        if obj.status == Task.STATUS_PENDING:
            return True
        from apps.jobs.services import JobService
        return (obj.assignee_id == request.user.pk
                or JobService.user_can_manage(request.user, obj.job))


class TaskDetailSerializer(TaskSerializer):
    job = serializers.SerializerMethodField()
    blep_minimum_minutes = serializers.SerializerMethodField()

    class Meta(TaskSerializer.Meta):
        fields = TaskSerializer.Meta.fields + ['job', 'blep_minimum_minutes']

    def get_job(self, obj):
        job = obj.job
        return {
            'id': job.pk,
            'job_number': job.job_number,
            'name': job.name,
            'status': job.status,
        }

    def get_blep_minimum_minutes(self, obj):
        from apps.jobs.services import blep_minimum_minutes
        return blep_minimum_minutes()
