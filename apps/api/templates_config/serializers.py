from rest_framework import serializers
from apps.estimates.models import (
    WorkTemplate, ServiceItem, TemplateTaskAssociation,
)
from apps.core.models import Configuration, AccountingCategory
from apps.inventory.models import TemplateMaterialAssociation


class ServiceItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceItem
        fields = [
            'template_id', 'template_name', 'description', 'is_active',
            'rate_scheme', 'default_active_modifiers', 'default_billable_qty',
        ]
        read_only_fields = ['template_id']

    def validate_rate_scheme(self, value):
        from apps.jobs.models import RateScheme
        if value and value.algorithm == RateScheme.PERCENTAGE:
            raise serializers.ValidationError(
                'Percentage services are document adjustments and cannot bill a task.'
            )
        return value


class TemplateAssociationSerializer(serializers.ModelSerializer):
    service_item = ServiceItemSerializer(read_only=True)

    class Meta:
        model = TemplateTaskAssociation
        fields = [
            'id', 'service_item', 'est_qty', 'sort_order',
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
            'associations',
        ]
        read_only_fields = ['template_id']


class TemplateMaterialAssociationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TemplateMaterialAssociation
        fields = [
            'template_material_association_id', 'work_template',
            'inventory_item', 'template_task_association',
            'quantity', 'sort_order',
        ]
        read_only_fields = ['template_material_association_id', 'work_template']


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
