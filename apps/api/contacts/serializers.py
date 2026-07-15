from rest_framework import serializers
from apps.contacts.models import Contact, Business, PaymentTerms, Tag
from apps.jobs.models import Job
from apps.api.jobs.serializers import JobSummarySerializer


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['tag_id', 'name']


class BusinessSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Business
        fields = ['business_id', 'business_name', 'our_reference_code', 'default_contact']


class ContactSummarySerializer(serializers.ModelSerializer):
    name = serializers.CharField(read_only=True)

    class Meta:
        model = Contact
        fields = ['contact_id', 'name', 'email', 'mobile_number']


class ContactSerializer(serializers.ModelSerializer):
    name = serializers.CharField(read_only=True)
    # Declared explicitly (not auto-generated) so DRF does NOT attach its own
    # UniqueValidator here — a duplicate email needs to surface a rich 409
    # (which existing contact conflicted), which only ContactService's
    # proactive check + ContactViewSet.create() can produce. Letting DRF's
    # validator fire first would short-circuit is_valid() with a bare
    # "already exists" message before that check ever runs. Uniqueness is
    # still enforced — by the service check and, as a backstop, the DB
    # constraint via full_clean().
    email = serializers.EmailField()
    business = BusinessSummarySerializer(read_only=True)
    business_id = serializers.PrimaryKeyRelatedField(
        queryset=Business.objects.all(), source='business', write_only=True, required=False, allow_null=True,
    )
    tags = TagSerializer(many=True, read_only=True)

    class Meta:
        model = Contact
        fields = [
            'contact_id', 'first_name', 'middle_initial', 'last_name', 'name',
            'email', 'mobile_number', 'work_number', 'home_number',
            'addr1', 'addr2', 'addr3', 'city', 'municipality',
            'postal_code', 'country_code', 'business', 'business_id', 'tags',
        ]
        read_only_fields = ['contact_id']


class BusinessSerializer(serializers.ModelSerializer):
    # Declared explicitly (not auto-generated) so DRF does NOT attach its own
    # UniqueValidator here — same reasoning as ContactSerializer.email above:
    # a duplicate name needs to surface a rich 409 (which existing business
    # conflicted), which only ContactService's proactive check + the
    # BusinessViewSet.create() override can produce. Uniqueness is still
    # enforced — by the service check and, as a backstop, the DB constraint
    # via full_clean().
    business_name = serializers.CharField(max_length=255)
    default_contact = ContactSerializer(read_only=True)
    default_contact_id = serializers.PrimaryKeyRelatedField(
        queryset=Contact.objects.all(), source='default_contact', write_only=True, required=False,
    )
    tags = TagSerializer(many=True, read_only=True)

    class Meta:
        model = Business
        fields = [
            'business_id', 'our_reference_code', 'business_name',
            'business_address', 'business_phone', 'tax_exemption_number',
            'website', 'terms', 'default_contact', 'default_contact_id', 'tax_multiplier',
            'qbo_customer_id', 'qbo_vendor_id', 'tags',
        ]
        read_only_fields = ['business_id', 'our_reference_code', 'qbo_customer_id', 'qbo_vendor_id']


class BusinessDetailSerializer(BusinessSerializer):
    contacts = ContactSummarySerializer(many=True, read_only=True)
    jobs = serializers.SerializerMethodField()

    class Meta(BusinessSerializer.Meta):
        fields = BusinessSerializer.Meta.fields + ['contacts', 'jobs']

    def get_jobs(self, obj):
        jobs = Job.objects.filter(contact__business=obj).order_by('-created_date')
        return JobSummarySerializer(jobs, many=True).data


class ContactDetailSerializer(ContactSerializer):
    business = BusinessSerializer(read_only=True)
    jobs = serializers.SerializerMethodField()

    class Meta(ContactSerializer.Meta):
        fields = ContactSerializer.Meta.fields + ['jobs']

    def get_jobs(self, obj):
        jobs = Job.objects.filter(contact=obj).order_by('-created_date')
        return JobSummarySerializer(jobs, many=True).data


class PaymentTermsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTerms
        fields = '__all__'
