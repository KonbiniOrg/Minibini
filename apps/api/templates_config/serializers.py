from rest_framework import serializers
from apps.estimates.models import (
    WorkTemplate, ServiceItem, TemplateTaskAssociation,
)
from apps.core.models import Configuration, AccountingCategory
from apps.inventory.models import TemplateMaterialAssociation


class ServiceItemSerializer(serializers.ModelSerializer):
    # Read-only rate snapshot so the Add Line picker can show price/unit per row
    # without a second fetch (the saved-work item prices via its RateScheme).
    rate_scheme_detail = serializers.SerializerMethodField()

    class Meta:
        model = ServiceItem
        fields = [
            'template_id', 'template_name', 'description', 'is_active',
            'rate_scheme', 'rate_scheme_detail',
            'default_active_modifiers',
        ]
        read_only_fields = ['template_id']

    def get_rate_scheme_detail(self, obj):
        rs = getattr(obj, 'rate_scheme', None)
        if not rs:
            return None
        return {
            'rate_scheme_id': rs.rate_scheme_id, 'name': rs.name,
            'rate': str(rs.rate), 'unit_label': rs.unit_label,
            'algorithm': rs.algorithm,
        }

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
            'is_product_structure', 'base_price',
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
    is_referenced = serializers.SerializerMethodField()

    class Meta:
        model = AccountingCategory
        fields = [
            'id', 'code', 'name', 'taxable', 'is_deposit',
            'default_description', 'is_active',
            'qbo_item_id', 'qbo_expense_account_id', 'is_referenced',
        ]
        read_only_fields = ['id', 'is_referenced']

    def get_is_referenced(self, obj):
        return obj.is_referenced()
