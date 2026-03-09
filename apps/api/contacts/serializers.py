from rest_framework import serializers
from apps.contacts.models import Contact, Business, PaymentTerms


class BusinessSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Business
        fields = ['business_id', 'business_name', 'our_reference_code']


class ContactSerializer(serializers.ModelSerializer):
    name = serializers.CharField(read_only=True)
    business = BusinessSummarySerializer(read_only=True)
    business_id = serializers.PrimaryKeyRelatedField(
        queryset=Business.objects.all(), source='business', write_only=True, required=False, allow_null=True,
    )

    class Meta:
        model = Contact
        fields = [
            'contact_id', 'first_name', 'middle_initial', 'last_name', 'name',
            'email', 'mobile_number', 'work_number', 'home_number',
            'addr1', 'addr2', 'addr3', 'city', 'municipality',
            'postal_code', 'country_code', 'business', 'business_id',
        ]
        read_only_fields = ['contact_id']


class BusinessSerializer(serializers.ModelSerializer):
    default_contact = ContactSerializer(read_only=True)

    class Meta:
        model = Business
        fields = [
            'business_id', 'our_reference_code', 'business_name',
            'business_address', 'business_phone', 'tax_exemption_number',
            'website', 'terms', 'default_contact', 'tax_multiplier',
        ]
        read_only_fields = ['business_id', 'our_reference_code']


class PaymentTermsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTerms
        fields = '__all__'
