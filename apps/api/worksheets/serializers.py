from decimal import Decimal
from rest_framework import serializers
from apps.estimates.models import EstWorksheet, WorkTemplate
from apps.jobs.models import PlanTask
from apps.inventory.models import PlanMaterial
from apps.core.models import AccountingCategory
from apps.core.units import UnitsField
from apps.api.mixins import JobScopedCanManageMixin


class PlanMaterialSerializer(serializers.ModelSerializer):
    units = UnitsField(read_only=True)

    class Meta:
        model = PlanMaterial
        fields = [
            'plan_material_id', 'description', 'quantity',
            'unit_cost', 'sell_price', 'inventory_item',
            'accounting_category', 'units',
        ]
        read_only_fields = fields


class PlanMaterialWriteSerializer(serializers.ModelSerializer):
    """Writable serializer for PlanMaterial; used by worksheet plan-materials endpoint."""
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
        model = PlanMaterial
        fields = [
            'plan_material_id', 'plan_task', 'description', 'quantity',
            'units', 'unit_cost', 'sell_price', 'inventory_item',
            'accounting_category', 'propagate_to_pli',
        ]
        read_only_fields = ['plan_material_id']

    def update(self, instance, validated_data):
        from apps.inventory.serializer_helpers import (
            enforce_pli_linked_allowlist, PLI_LINKED_PRICING_ALLOWED,
            PLAN_MATERIAL_FREEFORM_ALLOWED,
        )
        # plan_task is reassignable on both freeform and PLI-linked rows;
        # exclude it from the allowlist check.
        scratch = dict(validated_data)
        scratch.pop('plan_task', None)
        if instance.inventory_item_id is not None:
            enforce_pli_linked_allowlist(
                instance, scratch, PLI_LINKED_PRICING_ALLOWED,
            )
        else:
            disallowed = set(scratch.keys()) - PLAN_MATERIAL_FREEFORM_ALLOWED
            if disallowed:
                raise serializers.ValidationError({
                    'detail': f'Disallowed fields on freeform PlanMaterial: {sorted(disallowed)}',
                })
        validated_data.pop('propagate_to_pli', None)
        return super().update(instance, validated_data)


class PlanTaskSerializer(serializers.ModelSerializer):
    plan_materials = PlanMaterialSerializer(many=True, read_only=True)
    amount = serializers.SerializerMethodField()
    units = serializers.SerializerMethodField()

    class Meta:
        model = PlanTask
        fields = [
            'plan_task_id', 'name', 'description', 'sort_order',
            'service_price', 'active_modifiers', 'est_qty', 'est_worker_time',
            'amount', 'units', 'plan_materials',
        ]
        read_only_fields = ['plan_task_id', 'sort_order', 'amount', 'units']

    def get_amount(self, obj):
        return str(obj.compute_amount().quantize(Decimal('0.01')))

    def get_units(self, obj):
        return obj.service_price.unit_label if obj.service_price_id else ''


class PlanMaterialAssignTaskSerializer(serializers.Serializer):
    plan_task = serializers.PrimaryKeyRelatedField(
        queryset=PlanTask.objects.all(), allow_null=True,
    )


class EstWorksheetSerializer(JobScopedCanManageMixin, serializers.ModelSerializer):
    can_manage_job_path = 'job'
    tasks = PlanTaskSerializer(source='plan_tasks', many=True, read_only=True)
    taskless_materials = serializers.SerializerMethodField()
    job_number = serializers.SerializerMethodField()
    job_name = serializers.SerializerMethodField()
    # Derived: editable while the job's live estimate is draft/absent, frozen
    # once it's sent (see WorksheetService.is_editable).
    editable = serializers.SerializerMethodField()
    # Derived: deletable unless an atom is claimed by an estimate line item —
    # mirrors WorksheetService.delete_worksheet so the UI can suppress the
    # Delete button instead of letting the user hit a 400.
    deletable = serializers.SerializerMethodField()
    # Write-only: lets the create endpoint accept a WorkTemplate id to populate
    # tasks/materials from at create time. Not stored on the worksheet.
    template = serializers.PrimaryKeyRelatedField(
        queryset=WorkTemplate.objects.all(),
        write_only=True, required=False, allow_null=True,
    )

    class Meta:
        model = EstWorksheet
        fields = [
            'est_worksheet_id', 'job', 'job_number', 'job_name',
            'template', 'created_date', 'editable', 'deletable',
            'tasks', 'taskless_materials', 'can_manage',
        ]
        read_only_fields = ['est_worksheet_id', 'created_date']

    def get_editable(self, obj):
        from apps.estimates.services import WorksheetService
        return WorksheetService.is_editable(obj)

    def get_deletable(self, obj):
        from apps.estimates.services import WorksheetService
        return not WorksheetService.has_claimed_atoms(obj)

    def get_taskless_materials(self, obj):
        materials = PlanMaterial.objects.filter(
            est_worksheet=obj, plan_task__isnull=True,
        )
        return PlanMaterialSerializer(materials, many=True).data

    def get_job_number(self, obj):
        return obj.job.job_number if obj.job_id else None

    def get_job_name(self, obj):
        return obj.job.name if obj.job_id else ''
