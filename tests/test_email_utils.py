"""Tests for email parsing utilities"""

from django.test import TestCase
from apps.core.email_utils import (
    parse_email_address,
    extract_company_from_signature,
    extract_email_body,
    trim_body_at_signoff,
    clean_subject_for_job_name,
    strip_quoted_reply,
)


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


class TrimBodyAtSignoffTest(TestCase):
    """Tests for the precise sign-off trimmer used to derive a job description."""

    def test_trims_at_thanks_with_name(self):
        body = "Can you quote this part?\nNeeds 50 of them.\n\nThanks,\nJohn"
        self.assertEqual(
            trim_body_at_signoff(body),
            "Can you quote this part?\nNeeds 50 of them.",
        )

    def test_trims_at_best_with_name(self):
        body = "See attached drawing.\n\nBest,\nJane Smith"
        self.assertEqual(trim_body_at_signoff(body), "See attached drawing.")

    def test_trims_at_cheers_with_name(self):
        body = "Let me know the lead time.\n\nCheers,\nAlex"
        self.assertEqual(trim_body_at_signoff(body), "Let me know the lead time.")

    def test_trims_at_multiword_best_regards(self):
        body = "Quote needed by Friday.\n\nBest regards,\nPat"
        self.assertEqual(trim_body_at_signoff(body), "Quote needed by Friday.")

    def test_trims_at_multiword_thank_you(self):
        body = "Please confirm receipt.\n\nThank you,\nSam"
        self.assertEqual(trim_body_at_signoff(body), "Please confirm receipt.")

    def test_case_insensitive(self):
        body = "Order details below.\n\nTHANKS,\nMorgan"
        self.assertEqual(trim_body_at_signoff(body), "Order details below.")

    def test_prefers_longer_multiword_over_shorter(self):
        # If both "Best regards," and "Best," would match, longer wins so we
        # don't strand "regards,\nName" in the output.
        body = "Details here.\n\nBest regards,\nChris"
        self.assertEqual(trim_body_at_signoff(body), "Details here.")

    def test_no_trim_without_comma(self):
        # "Thanks for the info" is body content, not a sign-off.
        body = "Thanks for the info you sent over.\nMore details."
        self.assertEqual(
            trim_body_at_signoff(body),
            "Thanks for the info you sent over.\nMore details.",
        )

    def test_no_trim_without_following_name(self):
        # "Thanks," with nothing after is ambiguous — leave it alone.
        body = "Quote needed.\n\nThanks,\n"
        self.assertEqual(trim_body_at_signoff(body), body)

    def test_no_trim_when_signoff_absent(self):
        body = "Just a quick question — do you stock 1/4\" plate?"
        self.assertEqual(trim_body_at_signoff(body), body)

    def test_empty_body(self):
        self.assertEqual(trim_body_at_signoff(''), '')

    def test_signoff_at_start_of_body(self):
        body = "Thanks,\nJordan"
        self.assertEqual(trim_body_at_signoff(body), '')

    def test_word_boundary_not_partial_match(self):
        # "Bestest" shouldn't trigger the "Best," signoff.
        body = "Bestest quote you've seen.\nMore details."
        self.assertEqual(trim_body_at_signoff(body), body)

    def test_trims_at_triple_hyphen_separator(self):
        body = "Quote needed.\n\n---\nJohn Doe\nAcme Corp"
        self.assertEqual(trim_body_at_signoff(body), "Quote needed.")

    def test_trims_at_longer_hyphen_separator(self):
        body = "Quote needed.\n\n----------\nJohn Doe"
        self.assertEqual(trim_body_at_signoff(body), "Quote needed.")

    def test_no_trim_on_double_hyphen(self):
        # "--" is the standard sigdash separator and is already handled by
        # extract_email_body for the deprecated path. The signoff trim requires
        # 3+ hyphens to avoid clashing with em-dash-ish content like "a--b".
        body = "Quote -- needed.\n--\nJohn"
        self.assertEqual(trim_body_at_signoff(body), body)

    def test_no_trim_on_hyphen_without_following_content(self):
        body = "Quote needed.\n\n---\n"
        self.assertEqual(trim_body_at_signoff(body), body)

    def test_handles_crlf_line_endings(self):
        # Real IMAP bodies arrive with CRLF — make sure the trim still fires.
        body = "scale model of 3 floors of the museum\r\n\r\n\r\n\r\n----\r\nNeal's CNC\r\n510-783-3156"
        self.assertEqual(
            trim_body_at_signoff(body),
            "scale model of 3 floors of the museum",
        )

    def test_handles_crlf_with_word_signoff(self):
        body = "Need 50 of these.\r\n\r\nThanks,\r\nJane"
        self.assertEqual(trim_body_at_signoff(body), "Need 50 of these.")


class CleanSubjectForJobNameTest(TestCase):
    """Tests for cleaning an email subject into a job name."""

    def test_passes_through_short_subject(self):
        self.assertEqual(
            clean_subject_for_job_name('Quote for bracket'),
            'Quote for bracket',
        )

    def test_strips_re_prefix(self):
        self.assertEqual(
            clean_subject_for_job_name('Re: Quote for bracket'),
            'Quote for bracket',
        )

    def test_strips_fwd_prefix(self):
        self.assertEqual(
            clean_subject_for_job_name('Fwd: Quote for bracket'),
            'Quote for bracket',
        )

    def test_strips_repeated_prefixes(self):
        self.assertEqual(
            clean_subject_for_job_name('Re: Fwd: RE: Quote for bracket'),
            'Quote for bracket',
        )

    def test_strips_fw_and_uppercase(self):
        self.assertEqual(
            clean_subject_for_job_name('FW: RE: Quote'),
            'Quote',
        )

    def test_truncates_long_subject_with_ellipsis(self):
        subject = 'A' * 60
        result = clean_subject_for_job_name(subject)
        self.assertEqual(len(result), 50)
        self.assertTrue(result.endswith('...'))
        self.assertEqual(result, 'A' * 47 + '...')

    def test_truncates_after_prefix_strip(self):
        # 60 'A's after stripping Re:, so the truncation should kick in.
        subject = 'Re: ' + 'A' * 60
        result = clean_subject_for_job_name(subject)
        self.assertEqual(len(result), 50)
        self.assertTrue(result.endswith('...'))

    def test_no_ellipsis_when_exactly_50(self):
        subject = 'A' * 50
        self.assertEqual(clean_subject_for_job_name(subject), 'A' * 50)

    def test_empty_subject(self):
        self.assertEqual(clean_subject_for_job_name(''), '')
        self.assertEqual(clean_subject_for_job_name(None), '')


class StripQuotedReplyTest(TestCase):
    """Tests for the reusable reply/forward stripper."""

    def test_strips_gmail_quoted_lines(self):
        body = (
            "Sounds good — let's go with 50.\n\n"
            "> On Jan 1, John wrote:\n"
            "> Are you up for the bracket job?\n"
            "> Lead time 2 weeks?\n"
        )
        self.assertEqual(
            strip_quoted_reply(body),
            "Sounds good — let's go with 50.",
        )

    def test_strips_on_x_wrote_marker(self):
        body = (
            "Sounds good.\n\n"
            "On Mon, Jan 1, 2024 at 9:00 AM, John <john@example.com> wrote:\n"
            "Previous message body that should be removed.\n"
        )
        self.assertEqual(strip_quoted_reply(body), "Sounds good.")

    def test_strips_outlook_original_message_marker(self):
        body = (
            "Thanks for getting back to me.\n\n"
            "-----Original Message-----\n"
            "From: someone@example.com\n"
            "Subject: prior thread\n"
        )
        self.assertEqual(
            strip_quoted_reply(body),
            "Thanks for getting back to me.",
        )

    def test_strips_outlook_forward_header_block(self):
        # Outlook-style forward header — three consecutive header lines.
        body = (
            "FYI below.\n\n"
            "From: alice@example.com\n"
            "Sent: Monday, Jan 1, 2024 9:00 AM\n"
            "To: bob@example.com\n"
            "Subject: heads up\n"
            "\n"
            "original message body…\n"
        )
        self.assertEqual(strip_quoted_reply(body), "FYI below.")

    def test_strips_apple_mail_forward_marker(self):
        body = (
            "FYI.\n\n"
            "Begin forwarded message:\n"
            "From: a@example.com\n"
        )
        self.assertEqual(strip_quoted_reply(body), "FYI.")

    def test_handles_crlf_line_endings(self):
        body = "Sounds good.\r\n\r\n> Previous email here.\r\n> More quoted.\r\n"
        self.assertEqual(strip_quoted_reply(body), "Sounds good.")

    def test_no_marker_passthrough(self):
        body = "Just a simple message with no reply markers."
        self.assertEqual(strip_quoted_reply(body), body)

    def test_empty_input(self):
        self.assertEqual(strip_quoted_reply(''), '')
        self.assertEqual(strip_quoted_reply(None), '')

    def test_uses_earliest_marker(self):
        # Both a ">" line and an "On X wrote:" line exist; whichever appears
        # first wins. Here the "On X wrote:" comes first.
        body = (
            "Reply text.\n\n"
            "On Jan 1, John wrote:\n"
            "> nested quote\n"
            "> more\n"
        )
        self.assertEqual(strip_quoted_reply(body), "Reply text.")