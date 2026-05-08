from rest_framework import serializers
from apps.estimates.models import (
    WorkTemplate, TaskTemplate, TemplateTaskAssociation,
)
from apps.core.models import Configuration, AccountingCategory
from apps.inventory.models import TemplateMaterial
from apps.core.units import UnitsField


class TaskTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskTemplate
        fields = [
            'template_id', 'template_name', 'description', 'is_active',
            'rate_scheme', 'default_active_modifiers', 'default_billable_qty',
        ]
        read_only_fields = ['template_id']


class TemplateAssociationSerializer(serializers.ModelSerializer):
    task_template = TaskTemplateSerializer(read_only=True)

    class Meta:
        model = TemplateTaskAssociation
        fields = [
            'id', 'task_template', 'est_qty', 'sort_order',
        ]
        read_only_fields = ['id']


class WorkTemplateSerializer(serializers.ModelSerializer):
    associations = TemplateAssociationSerializer(
        source='templatetaskassociation_set', many=True, read_only=True
    )

    class Meta:
        model = WorkTemplate
        fields = [
            'template_id', 'template_name', 'description',
            'is_active', 'associations',
        ]
        read_only_fields = ['template_id']


class TemplateMaterialSerializer(serializers.ModelSerializer):
    units = UnitsField(required=False)

    class Meta:
        model = TemplateMaterial
        fields = [
            'template_material_id', 'work_template', 'description', 'quantity',
            'units', 'unit_cost', 'sell_price', 'price_list_item', 'accounting_category',
            'sort_order',
        ]
        read_only_fields = ['template_material_id', 'work_template']

    def update(self, instance, validated_data):
        from apps.inventory.serializer_helpers import (
            TEMPLATE_PLI_LINKED_ALLOWED, TEMPLATE_FREEFORM_ALLOWED,
        )
        if instance.price_list_item_id is not None:
            disallowed = set(validated_data.keys()) - TEMPLATE_PLI_LINKED_ALLOWED
            if disallowed:
                raise serializers.ValidationError({
                    'detail': (
                        'PLI-linked TemplateMaterials are immutable except for '
                        'quantity and sort_order; '
                        f'disallowed fields: {sorted(disallowed)}'
                    )
                })
        else:
            disallowed = set(validated_data.keys()) - TEMPLATE_FREEFORM_ALLOWED
            if disallowed:
                raise serializers.ValidationError({
                    'detail': f'Disallowed fields on freeform TemplateMaterial: {sorted(disallowed)}',
                })
        return super().update(instance, validated_data)


class ConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Configuration
        fields = ['key', 'value']


class AccountingCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingCategory
        fields = [
            'id', 'code', 'name', 'taxable', 'default_description', 'is_active',
            'qbo_item_id', 'qbo_expense_account_id',
        ]
        read_only_fields = ['id']
