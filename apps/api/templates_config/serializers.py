from django.core.exceptions import ValidationError as DjangoValidationError
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
    # Read-only resolved price (scheme.effective_rate over this item's config)
    # so pickers can show the real per-unit/flat price without re-deriving the
    # scheme's algorithm-specific interpretation of default_active_modifiers.
    display_rate = serializers.SerializerMethodField()

    class Meta:
        model = ServiceItem
        fields = [
            'template_id', 'template_name', 'description', 'is_active',
            'rate_scheme', 'rate_scheme_detail',
            'default_active_modifiers', 'display_rate',
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

    def get_display_rate(self, obj):
        rs = getattr(obj, 'rate_scheme', None)
        if not rs:
            return None
        return str(rs.effective_rate(obj.default_active_modifiers))

    def validate_rate_scheme(self, value):
        from apps.jobs.models import RateScheme
        if value and value.algorithm == RateScheme.PERCENTAGE:
            raise serializers.ValidationError(
                'Percentage services are document adjustments and cannot bill a task.'
            )
        return value

    def validate(self, data):
        # Cross-field: the config's shape is scheme-owned (percent-style key
        # list vs. flat_fee's single amount entry) — delegate to
        # RateScheme.validate_item_config rather than re-deriving the shape
        # here. Partial updates (PATCH) may omit either field, so fall back
        # to the existing instance's current value for whichever is absent.
        rate_scheme = data.get('rate_scheme')
        if rate_scheme is None and self.instance is not None:
            rate_scheme = self.instance.rate_scheme
        if 'default_active_modifiers' in data:
            config = data['default_active_modifiers']
        elif self.instance is not None:
            config = self.instance.default_active_modifiers
        else:
            config = []
        if rate_scheme is not None:
            try:
                rate_scheme.validate_item_config(config)
            except DjangoValidationError as e:
                raise serializers.ValidationError(e.message_dict)
        return data


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
    is_referenced = serializers.SerializerMethodField()
    is_fallback = serializers.SerializerMethodField()

    class Meta:
        model = AccountingCategory
        fields = [
            'id', 'code', 'name', 'taxable', 'is_deposit',
            'default_description', 'is_active',
            'qbo_item_id', 'qbo_expense_account_id', 'is_referenced',
            'is_fallback',
        ]
        read_only_fields = ['id', 'is_referenced', 'is_fallback']

    def get_is_referenced(self, obj):
        return obj.is_referenced()

    def get_is_fallback(self, obj):
        # The configured fallback category's pk is resolved once per
        # request by the view (see AccountingCategoryViewSet.get_serializer_
        # context) and handed down via context — never a per-row query.
        # Fall back to a direct (still single, memoized-per-call) lookup
        # for any caller that doesn't populate the context (e.g. this
        # serializer used outside AccountingCategoryViewSet).
        if 'fallback_category_id' in self.context:
            fallback_id = self.context['fallback_category_id']
        else:
            fallback_id = _resolve_fallback_category_id()
        return fallback_id is not None and obj.pk == fallback_id


def _resolve_fallback_category_id():
    raw = Configuration.objects.filter(
        key='fallback_accounting_category').values_list('value', flat=True).first()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
