from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.contacts.models import Contact, Business, PaymentTerms
from .base import FixtureTestCase


class ContactModelFixtureTest(FixtureTestCase):
    """
    Test Contact model using fixture data loaded from unit_test_data.json
    """

    def test_contacts_exist_from_fixture(self):
        """Test that contacts from fixture data exist and have correct properties"""
        john_doe = Contact.objects.get(first_name="John", last_name="Doe")
        self.assertEqual(john_doe.email, "john.doe@example.com")
        self.assertEqual(john_doe.address(), "123 Main St, Anytown, ST 12345")
        self.assertEqual(john_doe.mobile_number, "555-123-4567")

        jane_smith = Contact.objects.get(first_name="Jane", last_name="Smith")
        self.assertEqual(jane_smith.email, "jane.smith@company.com")
        self.assertEqual(jane_smith.mobile_number, "555-987-6543")

        acme_vendor = Contact.objects.get(first_name="Acme", last_name="Vendor")
        self.assertEqual(acme_vendor.email, "vendor@acme.com")

    def test_contact_str_method_with_fixture_data(self):
        """Test contact string representation with fixture data"""
        contact = Contact.objects.get(first_name="John", last_name="Doe")
        self.assertEqual(str(contact), "John Doe")

    def test_contact_relationships_with_users(self):
        """Test that contacts are properly linked to users"""
        from apps.core.models import User

        john_contact = Contact.objects.get(first_name="John", last_name="Doe")
        admin_user = User.objects.get(username="admin")
        self.assertEqual(admin_user.contact, john_contact)

        jane_contact = Contact.objects.get(first_name="Jane", last_name="Smith")
        manager_user = User.objects.get(username="manager1")
        self.assertEqual(manager_user.contact, jane_contact)

    def test_contact_relationships_with_jobs(self):
        """Test that contacts are properly linked to jobs"""
        from apps.jobs.models import Job

        john_contact = Contact.objects.get(first_name="John", last_name="Doe")
        job1 = Job.objects.get(job_number="JOB-2024-0001")
        self.assertEqual(job1.contact, john_contact)

    def test_create_new_contact(self):
        """Test creating a new contact alongside existing fixture data"""
        new_contact = Contact.objects.create(
            first_name='New Customer',
            last_name='',
            email="new@customer.com",
            mobile_number="555-000-0000"
        )
        self.assertEqual(new_contact.name, "New Customer")
        self.assertEqual(Contact.objects.count(), 5)  # 4 from fixture + 1 new


class PaymentTermsModelFixtureTest(FixtureTestCase):
    """
    Test PaymentTerms model using fixture data
    """

    def test_payment_terms_exist_from_fixture(self):
        """Test that payment terms from fixture exist"""
        terms1 = PaymentTerms.objects.get(pk=1)
        terms2 = PaymentTerms.objects.get(pk=2)
        self.assertIsNotNone(terms1)
        self.assertIsNotNone(terms2)

    def test_payment_terms_business_relationships(self):
        """Test that payment terms are properly linked to businesses"""
        terms1 = PaymentTerms.objects.get(pk=1)
        business1 = Business.objects.get(business_name="ABC Corporation")
        self.assertEqual(business1.terms, terms1)

        terms2 = PaymentTerms.objects.get(pk=2)
        business2 = Business.objects.get(business_name="XYZ Industries")
        self.assertEqual(business2.terms, terms2)

    def test_create_new_payment_terms(self):
        """Test creating new payment terms alongside existing fixture data"""
        new_terms = PaymentTerms.objects.create()
        self.assertIsNotNone(new_terms.term_id)
        self.assertEqual(PaymentTerms.objects.count(), 3)  # 2 from fixture + 1 new


class BusinessModelFixtureTest(FixtureTestCase):
    """
    Test Business model using fixture data
    """

    def test_businesses_exist_from_fixture(self):
        """Test that businesses from fixture data exist and have correct properties"""
        abc_corp = Business.objects.get(business_name="ABC Corporation")
        self.assertEqual(abc_corp.our_reference_code, "CUST001")
        self.assertEqual(abc_corp.business_phone, "123-456-7890")
        self.assertEqual(abc_corp.tax_exemption_number, "TX123456789")
        self.assertEqual(abc_corp.website, "https://www.abccorp.com")

        xyz_industries = Business.objects.get(business_name="XYZ Industries")
        self.assertEqual(xyz_industries.our_reference_code, "CUST002")
        self.assertEqual(xyz_industries.business_phone, "987-654-3210")
        self.assertEqual(xyz_industries.tax_exemption_number, "")  # Empty in fixture
        self.assertEqual(xyz_industries.website, "")  # Empty in fixture

    def test_business_str_method_with_fixture_data(self):
        """Test business string representation with fixture data"""
        business = Business.objects.get(business_name="ABC Corporation")
        self.assertEqual(str(business), "ABC Corporation")

    def test_business_payment_terms_relationships(self):
        """Test that businesses are properly linked to payment terms"""
        abc_corp = Business.objects.get(business_name="ABC Corporation")
        self.assertEqual(abc_corp.terms.pk, 1)

        xyz_industries = Business.objects.get(business_name="XYZ Industries")
        self.assertEqual(xyz_industries.terms.pk, 2)

    def test_business_optional_fields(self):
        """Test businesses with optional fields from fixture data"""
        xyz_industries = Business.objects.get(business_name="XYZ Industries")
        self.assertEqual(xyz_industries.tax_exemption_number, "")
        self.assertEqual(xyz_industries.website, "")

    def test_create_new_business(self):
        """Test creating a new business alongside existing fixture data"""
        terms = PaymentTerms.objects.get(pk=1)
        default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')
        new_business = Business.objects.create(
            our_reference_code="CUST003",
            business_name="New Business LLC",
            business_address="789 New St, Town, ST 44444",
            terms=terms,
            default_contact=default_contact
        )
        self.assertEqual(new_business.business_name, "New Business LLC")
        self.assertEqual(Business.objects.count(), 3)  # 2 from fixture + 1 new

    def test_business_cascade_behavior_with_payment_terms(self):
        """Test that business handles payment terms deletion correctly"""
        # Get a business and its payment terms
        business = Business.objects.get(business_name="ABC Corporation")
        original_terms = business.terms

        # Delete the payment terms (should set business.terms to NULL due to SET_NULL)
        original_terms.delete()

        # Refresh business from database
        business.refresh_from_db()
        self.assertIsNone(business.terms)
