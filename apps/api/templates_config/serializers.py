from rest_framework import serializers
from apps.estimates.models import (
    WorkTemplate, TaskTemplate, TemplateTaskAssociation,
)
from apps.core.models import Configuration, AccountingCategory
from apps.core.units import UnitsField
from apps.inventory.models import TemplateMaterial


class TaskTemplateSerializer(serializers.ModelSerializer):
    units = UnitsField()

    class Meta:
        model = TaskTemplate
        fields = [
            'template_id', 'template_name', 'description',
            'units', 'rate', 'accounting_category', 'is_active',
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
    class Meta:
        model = TemplateMaterial
        fields = [
            'template_material_id', 'work_template', 'description', 'quantity',
            'unit_cost', 'sell_price', 'price_list_item', 'accounting_category',
            'sort_order',
        ]
        read_only_fields = ['template_material_id', 'work_template']


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
