from rest_framework import serializers
from apps.estimates.models import (
    WorkOrderTemplate, TaskTemplate, TemplateTaskAssociation, TemplateBundle,
)
from apps.core.models import Configuration, AccountingCategory


class TaskTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskTemplate
        fields = [
            'template_id', 'template_name', 'description',
            'units', 'rate', 'accounting_category', 'is_active',
        ]
        read_only_fields = ['template_id']


class TemplateBundleSerializer(serializers.ModelSerializer):
    class Meta:
        model = TemplateBundle
        fields = [
            'id', 'name', 'description',
            'accounting_category', 'sort_order',
        ]
        read_only_fields = ['id']


class TemplateAssociationSerializer(serializers.ModelSerializer):
    task_template = TaskTemplateSerializer(read_only=True)

    class Meta:
        model = TemplateTaskAssociation
        fields = [
            'id', 'task_template', 'est_qty',
            'sort_order', 'mapping_strategy', 'bundle',
        ]
        read_only_fields = ['id']


class WorkOrderTemplateSerializer(serializers.ModelSerializer):
    associations = TemplateAssociationSerializer(
        source='templatetaskassociation_set', many=True, read_only=True
    )
    bundles = TemplateBundleSerializer(many=True, read_only=True)

    class Meta:
        model = WorkOrderTemplate
        fields = [
            'template_id', 'template_name', 'description',
            'is_active', 'associations', 'bundles',
        ]
        read_only_fields = ['template_id']


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
