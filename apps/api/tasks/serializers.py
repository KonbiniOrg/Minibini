from rest_framework import serializers

from apps.api.mixins import JobScopedCanManageMixin, InvoiceRefMixin
from apps.jobs.models import Task
from apps.inventory.models import Material
from apps.core.models import AccountingCategory
from apps.core.units import UnitsField


class MaterialSerializer(InvoiceRefMixin, serializers.ModelSerializer):
    invoice_source_type = 'material'
    is_expense_bound = serializers.BooleanField(read_only=True)
    inventory_item_is_catalog = serializers.SerializerMethodField()
    invoice = serializers.SerializerMethodField()

    class Meta:
        model = Material
        fields = [
            'material_id', 'description', 'quantity',
            'units', 'unit_cost', 'sell_price', 'inventory_item',
            'accounting_category',
            'consumption_state', 'restocked_qty',
            'is_expense_bound', 'inventory_item_is_catalog',
            'invoice',
        ]
        read_only_fields = fields

    def get_inventory_item_is_catalog(self, obj):
        return bool(obj.inventory_item and obj.inventory_item.is_catalog)


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

    class Meta:
        model = Material
        fields = [
            'material_id', 'description', 'quantity',
            'units', 'unit_cost', 'sell_price', 'inventory_item',
            'accounting_category', 'propagate_to_pli',
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
    """Serializer for tasks nested under /api/jobs/{id}/tasks/."""
    can_manage_job_path = 'job'
    invoice_source_type = 'task'
    assignee_name = serializers.SerializerMethodField()
    actual_hours = serializers.SerializerMethodField()
    scheme_name = serializers.CharField(source='service_price.name', read_only=True, default=None)
    scheme_algorithm = serializers.CharField(source='service_price.algorithm', read_only=True, default=None)
    scheme_unit_label = serializers.CharField(source='service_price.unit_label', read_only=True, default=None)
    effective_rate = serializers.SerializerMethodField()
    computed_charge = serializers.SerializerMethodField()
    has_active_blep = serializers.SerializerMethodField()
    active_worker_count = serializers.SerializerMethodField()
    has_bleps = serializers.SerializerMethodField()
    invoice = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'task_id', 'name', 'description', 'sort_order', 'status',
            'blocked_reason',
            'parent_task', 'assignee', 'assignee_name', 'worker_queue',
            'service_price', 'active_modifiers',
            'est_qty', 'est_worker_time', 'actual_qty',
            'scheme_name', 'scheme_algorithm', 'scheme_unit_label',
            'effective_rate', 'computed_charge',
            'actual_hours',
            'has_active_blep', 'active_worker_count', 'has_bleps',
            'can_manage',
            'invoice',
        ]
        read_only_fields = ['task_id', 'sort_order', 'status']

    def validate_service_price(self, value):
        from apps.jobs.models import ServicePrice
        if value and value.algorithm == ServicePrice.PERCENTAGE:
            raise serializers.ValidationError(
                'Percentage services are document adjustments and cannot bill a task.'
            )
        return value

    def get_assignee_name(self, obj):
        if obj.assignee:
            name = obj.assignee.get_full_name()
            return name if name else obj.assignee.username
        return None

    def get_actual_hours(self, obj):
        total_seconds = sum(
            b.elapsed.total_seconds()
            for b in obj.blep_set.all() if b.elapsed is not None
        )
        return round(total_seconds / 3600.0, 2)

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
