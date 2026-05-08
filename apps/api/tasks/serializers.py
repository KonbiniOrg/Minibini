from rest_framework import serializers

from apps.jobs.models import Task
from apps.inventory.models import Material
from apps.core.units import UnitsField


class MaterialSerializer(serializers.ModelSerializer):
    is_expense_bound = serializers.BooleanField(read_only=True)
    price_list_item_is_inventoried = serializers.SerializerMethodField()

    class Meta:
        model = Material
        fields = [
            'material_id', 'description', 'quantity',
            'units', 'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category',
            'consumption_state', 'restocked_qty',
            'is_expense_bound', 'price_list_item_is_inventoried',
        ]
        read_only_fields = fields

    def get_price_list_item_is_inventoried(self, obj):
        return bool(obj.price_list_item and obj.price_list_item.is_inventoried)


class MaterialWriteSerializer(serializers.ModelSerializer):
    units = UnitsField(required=False)
    propagate_to_pli = serializers.BooleanField(
        write_only=True, required=False,
    )

    class Meta:
        model = Material
        fields = [
            'material_id', 'description', 'quantity',
            'units', 'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category', 'propagate_to_pli',
        ]
        read_only_fields = ['material_id']

    def update(self, instance, validated_data):
        from apps.inventory.serializer_helpers import (
            enforce_pli_linked_allowlist, PLI_LINKED_PRICING_ALLOWED, FREEFORM_ALLOWED,
        )
        if instance.price_list_item_id is not None:
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


class TaskSerializer(serializers.ModelSerializer):
    """Serializer for tasks nested under /api/jobs/{id}/tasks/."""
    assignee_name = serializers.SerializerMethodField()
    actual_hours = serializers.SerializerMethodField()
    scheme_name = serializers.CharField(source='rate_scheme.name', read_only=True, default=None)
    scheme_algorithm = serializers.CharField(source='rate_scheme.algorithm', read_only=True, default=None)
    scheme_unit_label = serializers.CharField(source='rate_scheme.unit_label', read_only=True, default=None)
    effective_rate = serializers.SerializerMethodField()
    computed_charge = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'task_id', 'name', 'description', 'sort_order', 'status',
            'blocked_reason',
            'parent_task', 'assignee', 'assignee_name', 'worker_queue',
            'rate_scheme', 'active_modifiers',
            'est_qty', 'est_worker_time', 'actual_qty',
            'scheme_name', 'scheme_algorithm', 'scheme_unit_label',
            'effective_rate', 'computed_charge',
            'actual_hours',
        ]
        read_only_fields = ['task_id', 'sort_order', 'status']

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


class TaskDetailSerializer(TaskSerializer):
    job = serializers.SerializerMethodField()

    class Meta(TaskSerializer.Meta):
        fields = TaskSerializer.Meta.fields + ['job']

    def get_job(self, obj):
        job = obj.job
        return {
            'id': job.pk,
            'job_number': job.job_number,
            'name': job.name,
            'status': job.status,
        }
