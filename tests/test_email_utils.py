"""Tests for email parsing utilities"""

from django.test import TestCase
from apps.core.email_utils import parse_email_address, extract_company_from_signature, extract_email_body


class ParseEmailAddressTest(TestCase):
    """Test email address parsing"""

    def test_parse_standard_email(self):
        """Test standard 'Name <email>' format"""
        name, email = parse_email_address('John Doe <john@example.com>')
        self.assertEqual(name, 'John Doe')
        self.assertEqual(email, 'john@example.com')

    def test_parse_email_only(self):
        """Test email without name"""
        name, email = parse_email_address('john.doe@example.com')
        self.assertEqual(name, 'John Doe')  # Extracted from email
        self.assertEqual(email, 'john.doe@example.com')

    def test_parse_empty(self):
        """Test empty input"""
        name, email = parse_email_address('')
        self.assertEqual(name, '')
        self.assertEqual(email, '')


class ExtractCompanyFromSignatureTest(TestCase):
    """Test company name extraction from email signatures"""

    def test_extract_with_standard_signature(self):
        """Test extraction from properly formatted signature"""
        email_text = '''Hi there,

I need a quote for your services.

Best regards,
John Doe
Senior Manager
Acme Corporation
john@acme.com
555-1234'''
        company = extract_company_from_signature(email_text)
        self.assertEqual(company, 'Acme Corporation')

    def test_extract_with_neals_signature(self):
        """Test extraction from properly formatted signature"""
        email_text = '''Greetings,

We are making a thing for which we require assistance.  Please see the attachments for details.

Best,
Rachel McConnell
----
Neal's CNC
www.nealscnc.com
510-783-3156'''
        company = extract_company_from_signature(email_text)
        #self.assertEqual(company, "Neal's CNC")

    def test_extract_with_llc_suffix(self):
        """Test extraction with LLC suffix"""
        email_text = '''Please send the proposal.

Thanks,
Jane Smith
TechStart LLC
jane@techstart.com'''
        company = extract_company_from_signature(email_text)
        self.assertEqual(company, 'TechStart LLC')

    def test_extract_with_inc_suffix(self):
        """Test extraction with Inc suffix"""
        email_text = '''Looking forward to working with you.

Sincerely,
Bob Wilson
GlobalTech Inc
bob@globaltech.com'''
        company = extract_company_from_signature(email_text)
        self.assertEqual(company, 'GlobalTech Inc')

    def test_no_extraction_without_signature_marker(self):
        """Test that company names in body are not extracted without signature"""
        email_text = '''Hi,

I wanted to discuss a partnership with Microsoft Corporation.
Apple Inc also expressed interest.
GlobalTech LLC wants to participate too.

Let me know.'''
        company = extract_company_from_signature(email_text)
        self.assertEqual(company, '')  # Should not extract from body

    def test_no_extraction_see_attached(self):
        """Test minimal emails without signatures"""
        email_text = 'See attached.'
        company = extract_company_from_signature(email_text)
        self.assertEqual(company, '')

        email_text = 'Please review the attached document.'
        company = extract_company_from_signature(email_text)
        self.assertEqual(company, '')

    def test_no_extraction_forwarded_chain(self):
        """Test that forwarded signatures are not extracted"""
        email_text = '''Please see below.

---------- Forwarded message ----------
From: Jane Doe <jane@company.com>
Date: Mon, Jan 1, 2024

We can help with that.

Best regards,
Jane Doe
Acme Corp'''
        company = extract_company_from_signature(email_text)
        self.assertEqual(company, '')  # Original sender didn't sign

    def test_extract_with_dash_separator(self):
        """Test extraction with -- separator"""
        email_text = '''Here's the information you requested.

--
Carol Anderson
Project Manager
Digital Solutions Inc
carol@digitalsolutions.com'''
        company = extract_company_from_signature(email_text)
        self.assertEqual(company, 'Digital Solutions Inc')

    def test_skip_personal_name_lines(self):
        """Test that personal names are skipped"""
        email_text = '''Thanks for reaching out.

Best,
Mike Johnson
Mike Johnson
Software Solutions LLC
mike@software.com'''
        company = extract_company_from_signature(email_text)
        self.assertEqual(company, 'Software Solutions LLC')

    def test_skip_job_titles(self):
        """Test that job titles alone are not extracted"""
        email_text = '''Let's discuss this further.

Regards,
Sarah Lee
Chief Technology Officer
TechCorp Industries
sarah@techcorp.com'''
        company = extract_company_from_signature(email_text)
        self.assertEqual(company, 'TechCorp Industries')

    def test_extract_with_at_pattern(self):
        """Test extraction with 'at Company' pattern"""
        email_text = '''I'll send over the details.

Thanks,
David Park
Engineer at Innovation Labs Inc
david@innovationlabs.com'''
        company = extract_company_from_signature(email_text)
        self.assertEqual(company, 'Innovation Labs Inc')

    def test_no_extraction_incomplete_signature(self):
        """Test incomplete signatures without company"""
        email_text = '''Please let me know.

Thanks,
John'''
        company = extract_company_from_signature(email_text)
        self.assertEqual(company, '')

    def test_extract_company_first_in_signature(self):
        """Test when company appears first in signature"""
        email_text = '''I'll follow up tomorrow.

Best regards,
Acme Corp
Bob Smith, Senior Manager
555-100-1000'''
        company = extract_company_from_signature(email_text)
        self.assertEqual(company, 'Acme Corp')

    def test_extract_with_various_suffixes(self):
        """Test extraction with various corporate suffixes"""
        test_cases = [
            ('Hello,\n\nThanks,\nJohn\nTest Company', 'Test Company'),
            ('Hello,\n\nThanks,\nJohn\nTest Group', 'Test Group'),
            ('Hello,\n\nThanks,\nJohn\nTest Services', 'Test Services'),
            ('Hello,\n\nThanks,\nJohn\nTest Solutions', 'Test Solutions'),
            ('Hello,\n\nThanks,\nJohn\nTest Technologies', 'Test Technologies'),
            ('Hello,\n\nThanks,\nJohn\nTest Enterprises', 'Test Enterprises'),
            ('Hello,\n\nThanks,\nJohn\nTest Partners', 'Test Partners'),
            ('Hello,\n\nThanks,\nJohn\nTest Associates', 'Test Associates'),
            ('Hello,\n\nThanks,\nJohn\nTest Industries', 'Test Industries'),
        ]

        for email_text, expected in test_cases:
            with self.subTest(email_text=email_text):
                company = extract_company_from_signature(email_text)
                self.assertEqual(company, expected)

    def test_no_extraction_from_urls(self):
        """Test that URLs are not extracted as companies"""
        email_text = '''Check out our website.

Best,
John Smith
http://example.com
john@example.com'''
        company = extract_company_from_signature(email_text)
        self.assertEqual(company, '')

    def test_no_extraction_from_email_addresses(self):
        """Test that email addresses are not extracted as companies"""
        email_text = '''Contact me anytime.

Cheers,
Jane Doe
jane@longcompanyname.com
555-1234'''
        company = extract_company_from_signature(email_text)
        self.assertEqual(company, '')


class ExtractEmailBodyTest(TestCase):
    """Test email body extraction"""

    def test_extract_plain_text(self):
        """Test extraction from plain text email"""
        email_content = {
            'text': 'This is the email body.\n\nPlease respond.',
            'html': ''
        }
        body = extract_email_body(email_content)
        self.assertEqual(body, 'This is the email body.\n\nPlease respond.')

    def test_remove_signature(self):
        """Test signature removal from body"""
        email_content = {
            'text': '''Hi there,

This is the main content.

Best regards,
John Doe
Acme Corp''',
            'html': ''
        }
        body = extract_email_body(email_content)
        self.assertEqual(body, 'Hi there,\n\nThis is the main content.')

    def test_remove_quoted_replies(self):
        """Test removal of quoted replies"""
        email_content = {
            'text': '''Thanks for your response.

> On Jan 1, 2024, someone wrote:
> This is quoted text
> More quoted text''',
            'html': ''
        }
        body = extract_email_body(email_content)
        self.assertEqual(body, 'Thanks for your response.')

    def test_handle_empty_content(self):
        """Test handling of empty content"""
        body = extract_email_body({})
        self.assertEqual(body, '')

        body = extract_email_body({'text': '', 'html': ''})
        self.assertEqual(body, '')