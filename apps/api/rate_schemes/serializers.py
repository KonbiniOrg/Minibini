from rest_framework import serializers
from apps.jobs.models import RateScheme


class RateSchemeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RateScheme
        fields = [
            'rate_scheme_id', 'name', 'description', 'algorithm',
            'rate', 'unit_label', 'minimum_charge',
            'modifiers', 'accounting_category',
        ]
        read_only_fields = ['rate_scheme_id']
