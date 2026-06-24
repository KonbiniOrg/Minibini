from rest_framework import serializers
from apps.jobs.models import ServicePrice
from apps.core.units import get_units_list


class ServicePriceSerializer(serializers.ModelSerializer):
    superseded = serializers.SerializerMethodField()
    reference_counts = serializers.SerializerMethodField()
    # unit_label is required + must be a configured unit for the task-billing
    # algorithms, but a `percentage` adjustment has no meaningful unit. Allow it
    # blank/absent at the field level and resolve it in validate() per algorithm.
    unit_label = serializers.CharField(
        required=False, allow_blank=True, max_length=50,
    )

    class Meta:
        model = ServicePrice
        fields = [
            'service_price_id', 'name', 'description', 'algorithm',
            'rate', 'unit_label',
            'modifiers', 'accounting_category',
            'replaced_by', 'replaced_at', 'superseded', 'reference_counts',
        ]
        read_only_fields = [
            'service_price_id', 'replaced_by', 'replaced_at',
            'superseded', 'reference_counts',
        ]

    def get_superseded(self, obj):
        return obj.replaced_by_id is not None

    def get_reference_counts(self, obj):
        return obj.reference_counts()

    def validate(self, attrs):
        # Resolve the effective algorithm + unit_label across create / full
        # update / partial update.
        algorithm = attrs.get('algorithm') or (
            self.instance.algorithm if self.instance else None
        )
        unit = attrs.get('unit_label')
        if unit is None and self.instance is not None:
            unit = self.instance.unit_label

        if algorithm == ServicePrice.PERCENTAGE:
            # A percentage service carries no unit; default to 'none' (and skip
            # the configured-unit check — the unit is cosmetic here).
            attrs['unit_label'] = unit or 'none'
        else:
            if not unit:
                raise serializers.ValidationError(
                    {'unit_label': 'This field is required.'}
                )
            if unit not in get_units_list():
                raise serializers.ValidationError(
                    {'unit_label': f'"{unit}" is not a configured unit.'}
                )
            attrs['unit_label'] = unit
        return attrs
