"""Tests for email parsing utilities"""

from django.test import TestCase
from apps.core.email_utils import (
    parse_email_address,
    extract_company_from_signature,
    extract_email_body,
    trim_body_at_signoff,
    clean_subject_for_job_name,
    strip_quoted_reply,
    resolve_contact_links,
    build_reply_subject,
    build_reply_body,
    collect_thread_member_ids,
)
from apps.contacts.models import Contact


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


class ResolveContactLinksTest(TestCase):
    """Map raw email addresses (as they appear in From/To/CC headers) to
    Contact rows so the email-detail view can render addresses as links."""

    def setUp(self):
        self.jane = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-1',
        )
        self.bob = Contact.objects.create(
            first_name='Bob', last_name='Smith',
            email='bob@example.com', mobile_number='555-2',
        )

    def test_resolves_bare_email(self):
        links = resolve_contact_links(['jane@example.com'])
        self.assertIn('jane@example.com', links)
        self.assertEqual(links['jane@example.com']['contact_id'], self.jane.contact_id)
        self.assertEqual(links['jane@example.com']['name'], 'Jane Doe')

    def test_resolves_name_bracket_format(self):
        links = resolve_contact_links(['Jane Doe <jane@example.com>'])
        self.assertIn('jane@example.com', links)
        self.assertEqual(links['jane@example.com']['contact_id'], self.jane.contact_id)

    def test_case_insensitive_email_match(self):
        links = resolve_contact_links(['JANE@Example.COM', 'Bob <BOB@example.com>'])
        self.assertIn('jane@example.com', links)
        self.assertIn('bob@example.com', links)

    def test_unknown_addresses_omitted(self):
        links = resolve_contact_links(['stranger@example.com', 'jane@example.com'])
        self.assertIn('jane@example.com', links)
        self.assertNotIn('stranger@example.com', links)

    def test_mixed_list(self):
        links = resolve_contact_links([
            'Jane <jane@example.com>',
            'Bob <bob@example.com>',
            'unknown@nowhere.com',
        ])
        self.assertEqual(set(links.keys()), {'jane@example.com', 'bob@example.com'})

    def test_empty_input(self):
        self.assertEqual(resolve_contact_links([]), {})
        self.assertEqual(resolve_contact_links(None), {})

    def test_empty_and_whitespace_strings_ignored(self):
        links = resolve_contact_links(['', '   ', None])
        self.assertEqual(links, {})

    def test_no_duplicate_queries_for_repeated_addresses(self):
        # Multiple references to the same address should collapse to a single
        # contact row in the result (and one DB query under the hood).
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        with CaptureQueriesContext(connection) as ctx:
            links = resolve_contact_links([
                'jane@example.com',
                'Jane Doe <jane@example.com>',
                'JANE@EXAMPLE.COM',
            ])
        self.assertEqual(len(links), 1)
        # One Contact SELECT — not one per address.
        select_queries = [q for q in ctx.captured_queries if q['sql'].lstrip().lower().startswith('select')]
        self.assertEqual(len(select_queries), 1, select_queries)


class BuildReplySubjectTest(TestCase):
    """Strip existing Re:/Fwd: prefixes, prefix exactly one Re:."""

    def test_bare_subject_gets_re_prefix(self):
        self.assertEqual(build_reply_subject('Quote for bracket'), 'Re: Quote for bracket')

    def test_already_re_prefixed_stays_single_re(self):
        self.assertEqual(build_reply_subject('Re: Quote'), 'Re: Quote')

    def test_repeated_re_collapses(self):
        self.assertEqual(build_reply_subject('Re: Re: Re: Quote'), 'Re: Quote')

    def test_fwd_prefix_replaced_by_re(self):
        self.assertEqual(build_reply_subject('Fwd: Quote'), 'Re: Quote')

    def test_mixed_re_and_fwd_collapses(self):
        self.assertEqual(build_reply_subject('Re: Fwd: RE: Quote'), 'Re: Quote')

    def test_case_insensitive(self):
        self.assertEqual(build_reply_subject('RE: Quote'), 'Re: Quote')

    def test_empty_subject_gets_no_subject_placeholder(self):
        self.assertEqual(build_reply_subject(''), 'Re: (no subject)')
        self.assertEqual(build_reply_subject(None), 'Re: (no subject)')

    def test_whitespace_only_subject_becomes_no_subject(self):
        self.assertEqual(build_reply_subject('   '), 'Re: (no subject)')


class BuildReplyBodyTest(TestCase):
    """Quoted-original block: blank lines for the user's reply, then
    attribution line, then > -prefixed parent body."""

    def _make_parent(self, *, from_email='Jane Doe <jane@example.com>',
                     text_body='Hi,\n\nCould you quote 50 brackets?\n',
                     date=None):
        from apps.core.models import EmailRecord, TempEmail
        from django.utils import timezone as tz
        record = EmailRecord.objects.create(message_id='<parent@example.com>')
        TempEmail.objects.create(
            email_record=record,
            uid='1',
            subject='Quote',
            from_email=from_email,
            to_email='us@example.com',
            date_sent=date or tz.now(),
            text_body=text_body,
        )
        return record

    def test_standard_quoted_original(self):
        from datetime import datetime
        from django.utils.timezone import make_aware
        parent = self._make_parent(
            date=make_aware(datetime(2026, 5, 28, 9, 32)),
        )
        body = build_reply_body(parent)
        self.assertTrue(body.startswith('\n\n'), 'leading blank lines for reply space')
        self.assertIn('On ', body)
        self.assertIn('Jane Doe', body)
        self.assertIn('jane@example.com', body)
        self.assertIn('wrote:', body)
        # Each line of the parent body gets > -prefixed.
        self.assertIn('> Hi,', body)
        self.assertIn('> Could you quote 50 brackets?', body)

    def test_empty_text_body_falls_back_to_placeholder(self):
        parent = self._make_parent(text_body='')
        body = build_reply_body(parent)
        self.assertIn('wrote:', body)
        self.assertIn('> (original message unavailable)', body)

    def test_already_quoted_parent_gets_re_prefixed(self):
        """Nested quote lines become >> ... so the thread depth grows visibly."""
        parent = self._make_parent(text_body='My reply.\n\n> Original line.\n')
        body = build_reply_body(parent)
        self.assertIn('> My reply.', body)
        self.assertIn('> > Original line.', body)

    def test_blank_lines_in_parent_become_bare_gt(self):
        """Blank lines get > -prefixed too, preserving the visual gap."""
        parent = self._make_parent(text_body='Line one\n\nLine three\n')
        body = build_reply_body(parent)
        # The empty middle line should appear as a bare '>' line.
        self.assertRegex(body, r'> Line one\n>\n> Line three')

    def test_no_display_name_uses_email_only_in_attribution(self):
        parent = self._make_parent(from_email='jane@example.com')
        body = build_reply_body(parent)
        # Attribution still readable; the spec allows fewer angle brackets
        # when there's no name to wrap.
        self.assertIn('jane@example.com', body)
        self.assertIn('wrote:', body)

    def test_no_temp_data_returns_just_blank_lines(self):
        from apps.core.models import EmailRecord
        parent = EmailRecord.objects.create(message_id='<no-temp@example.com>')
        body = build_reply_body(parent)
        # No attribution we can build; just the reply-space blank lines.
        self.assertEqual(body, '\n\n')


class CollectThreadMemberIdsTest(TestCase):
    """BFS over the RFC 5322 thread graph: Message-ID + In-Reply-To +
    References intersection."""

    def _make_email(self, message_id, *, in_reply_to='', references='',
                    direction=None):
        from apps.core.models import EmailRecord, TempEmail
        from django.utils import timezone as tz
        from apps.core.models import EmailRecord
        kwargs = {'message_id': message_id}
        if direction is not None:
            kwargs['direction'] = direction
        record = EmailRecord.objects.create(**kwargs)
        TempEmail.objects.create(
            email_record=record,
            uid=message_id.replace('<', '').replace('>', '')[:10],
            from_email='someone@example.com',
            to_email='us@example.com',
            date_sent=tz.now(),
            in_reply_to=in_reply_to,
            references=references,
        )
        return record

    def test_lone_email_returns_just_itself(self):
        e1 = self._make_email('<solo@example.com>')
        self.assertEqual(collect_thread_member_ids(e1), {e1.pk})

    def test_linear_chain_via_references(self):
        e1 = self._make_email('<m1@example.com>')
        e2 = self._make_email(
            '<m2@example.com>',
            in_reply_to='<m1@example.com>',
            references='<m1@example.com>',
        )
        e3 = self._make_email(
            '<m3@example.com>',
            in_reply_to='<m2@example.com>',
            references='<m1@example.com> <m2@example.com>',
        )
        e4 = self._make_email(
            '<m4@example.com>',
            in_reply_to='<m3@example.com>',
            references='<m1@example.com> <m2@example.com> <m3@example.com>',
        )

        # Linking from anywhere in the chain finds the whole chain.
        for source in (e1, e2, e3, e4):
            self.assertEqual(
                collect_thread_member_ids(source),
                {e1.pk, e2.pk, e3.pk, e4.pk},
                f'starting from {source.message_id}',
            )

    def test_reply_by_in_reply_to_only_no_references(self):
        e1 = self._make_email('<root@example.com>')
        e2 = self._make_email(
            '<child@example.com>',
            in_reply_to='<root@example.com>',
            # references intentionally blank — older mail clients sometimes
            # set In-Reply-To without populating References.
            references='',
        )
        self.assertEqual(
            collect_thread_member_ids(e1),
            {e1.pk, e2.pk},
        )

    def test_branching_thread(self):
        """Two replies to the same root, then a reply to one of them."""
        root = self._make_email('<root@example.com>')
        a = self._make_email(
            '<a@example.com>',
            in_reply_to='<root@example.com>',
            references='<root@example.com>',
        )
        b = self._make_email(
            '<b@example.com>',
            in_reply_to='<root@example.com>',
            references='<root@example.com>',
        )
        a_reply = self._make_email(
            '<a-reply@example.com>',
            in_reply_to='<a@example.com>',
            references='<root@example.com> <a@example.com>',
        )

        # Starting from any branch reaches the whole tree.
        for source in (root, a, b, a_reply):
            self.assertEqual(
                collect_thread_member_ids(source),
                {root.pk, a.pk, b.pk, a_reply.pk},
                f'starting from {source.message_id}',
            )

    def test_unrelated_threads_dont_mix(self):
        # Thread 1
        t1_root = self._make_email('<t1@example.com>')
        t1_reply = self._make_email(
            '<t1-r@example.com>',
            in_reply_to='<t1@example.com>',
            references='<t1@example.com>',
        )
        # Thread 2 — completely separate
        t2_root = self._make_email('<t2@example.com>')
        t2_reply = self._make_email(
            '<t2-r@example.com>',
            in_reply_to='<t2@example.com>',
            references='<t2@example.com>',
        )

        self.assertEqual(
            collect_thread_member_ids(t1_root),
            {t1_root.pk, t1_reply.pk},
        )
        self.assertEqual(
            collect_thread_member_ids(t2_root),
            {t2_root.pk, t2_reply.pk},
        )

    def test_outbound_emails_participate(self):
        """An outbound reply we sent is a member of the same thread."""
        from apps.core.models import EmailRecord
        inbound = self._make_email('<customer@example.com>')
        outbound = self._make_email(
            '<minibini-out@example.com>',
            in_reply_to='<customer@example.com>',
            references='<customer@example.com>',
            direction=EmailRecord.OUTBOUND,
        )
        self.assertEqual(
            collect_thread_member_ids(inbound),
            {inbound.pk, outbound.pk},
        )

    def test_email_without_temp_data_is_included_as_target(self):
        """An EmailRecord whose TempEmail was purged is still a thread
        member when its Message-ID appears in a sibling's references."""
        from apps.core.models import EmailRecord
        # Source has temp_data referencing a purged email.
        ancient = EmailRecord.objects.create(message_id='<ancient@example.com>')
        source = self._make_email(
            '<source@example.com>',
            references='<ancient@example.com>',
        )
        result = collect_thread_member_ids(source)
        self.assertIn(ancient.pk, result)
        self.assertIn(source.pk, result)

    def test_no_message_id_no_temp_data_returns_just_self(self):
        from apps.core.models import EmailRecord
        # Pathological: an EmailRecord that somehow has no message_id and
        # no temp_data. Defensive — should not crash.
        bare = EmailRecord.objects.create(message_id='<bare@example.com>')
        # No TempEmail created.
        self.assertEqual(collect_thread_member_ids(bare), {bare.pk})

    def test_bfs_converges_on_deep_chain(self):
        """A 10-deep chain — within the defensive iteration cap of 8 we
        still converge because each email's references encodes the full
        chain back to the root."""
        emails = []
        for i in range(10):
            mid = f'<m{i}@example.com>'
            irt = f'<m{i-1}@example.com>' if i > 0 else ''
            refs = ' '.join(f'<m{j}@example.com>' for j in range(i)) if i > 0 else ''
            emails.append(self._make_email(mid, in_reply_to=irt, references=refs))

        # Starting from the deepest gets the whole chain in one expansion
        # (its references field already enumerates them).
        result = collect_thread_member_ids(emails[-1])
        self.assertEqual(result, {e.pk for e in emails})

        # Starting from the root also reaches everyone.
        result = collect_thread_member_ids(emails[0])
        self.assertEqual(result, {e.pk for e in emails})