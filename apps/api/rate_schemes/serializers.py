from rest_framework import serializers
from apps.jobs.models import RateScheme
from apps.core.units import get_units_list


class RateSchemeSerializer(serializers.ModelSerializer):
    superseded = serializers.SerializerMethodField()
    reference_counts = serializers.SerializerMethodField()

    class Meta:
        model = RateScheme
        fields = [
            'rate_scheme_id', 'name', 'description', 'algorithm',
            'rate', 'unit_label',
            'modifiers', 'accounting_category',
            'replaced_by', 'replaced_at', 'superseded', 'reference_counts',
        ]
        read_only_fields = [
            'rate_scheme_id', 'replaced_by', 'replaced_at',
            'superseded', 'reference_counts',
        ]

    def get_superseded(self, obj):
        return obj.replaced_by_id is not None

    def get_reference_counts(self, obj):
        return obj.reference_counts()

    def validate_unit_label(self, value):
        allowed = get_units_list()
        if value not in allowed:
            raise serializers.ValidationError(
                f'"{value}" is not a configured unit.'
            )
        return value
