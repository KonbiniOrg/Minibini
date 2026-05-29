"""Utilities for parsing email data."""

import re
from email.utils import parseaddr


def parse_email_address(from_header):
    """
    Parse email From header to extract name and email address.

    Args:
        from_header (str): Email From header (e.g., "John Doe <john@example.com>")

    Returns:
        tuple: (name, email_address)

    Example:
        >>> parse_email_address("John Doe <john@example.com>")
        ('John Doe', 'john@example.com')
    """
    if not from_header:
        return ('', '')

    name, email = parseaddr(from_header)

    # If no name found, try to extract from email
    if not name and email:
        # Use part before @ as name
        name = email.split('@')[0].replace('.', ' ').replace('_', ' ').title()

    return (name.strip(), email.strip())


def extract_company_from_signature(email_text):
    """
    Attempt to extract company name from email signature.

    This is a heuristic approach looking for common signature patterns.
    Only looks at actual signature sections to avoid false positives from
    email body content or forwarded chains.

    Args:
        email_text (str): Full email text content

    Returns:
        str: Extracted company name or empty string
    """
    if not email_text:
        return ''

    # First check for forwarded message markers - we don't want to extract from forwarded content
    forward_markers = [
        r'------+\s*Forwarded\s+message',
        r'------+\s*Original\s+message',
        r'From:.*\nDate:.*\nSubject:',
        r'On\s+.+wrote:',
    ]

    # Find where forwarded content starts
    forward_position = len(email_text)
    for marker in forward_markers:
        match = re.search(marker, email_text, re.IGNORECASE | re.MULTILINE)
        if match:
            forward_position = min(forward_position, match.start())

    # Only look for signatures before any forwarded content
    search_text = email_text[:forward_position]

    # Common signature indicators - more specific patterns
    signature_markers = [
        r'\n--\s*\n',  # -- separator (must be on new line)
        r'\n----+\s*\n',  # ---- separator (4+ dashes)
        r'\n\s*Best regards',
        r'\n\s*Sincerely',
        r'\n\s*Regards',
        r'\n\s*Thank you',
        r'\n\s*Thanks',
        r'\n\s*Cheers',
        r'\n\s*Best,',
    ]

    # Find potential signature section
    signature_text = None
    for marker in signature_markers:
        match = re.search(marker, search_text, re.IGNORECASE)
        if match:
            # Get text after the marker
            signature_text = search_text[match.end():]
            break

    # If no signature marker found, return empty - don't guess from body
    if signature_text is None:
        return ''

    # Look for company name patterns in signature only
    # Pattern 1: Lines ending with "Inc", "LLC", "Ltd", "Corp" etc (strongest signal)
    # Pattern 2: "at Company Name" or "@ Company Name"
    # Pattern 3: Company name on its own line (but only with corporate suffixes)

    company_patterns = [
        # "at/@ Company" pattern - capture only the company name after "at" or "@" (check this first)
        r'\b(?:at|@)\s+([A-Z][A-Za-z0-9\s&,\.\-\']+(?:Inc|LLC|Ltd|Corp|Corporation|Co|Company|Group|Services|Solutions|Technologies|Enterprises|Partners|Associates|Industries)\.?)',
        # Strong patterns - corporate entities on their own line (not preceded by "at" or "@")
        r'^(?!.*\b(?:at|@)\s+)([A-Z][A-Za-z0-9\s&,\.\-\']+(?:Inc|LLC|Ltd|Corp|Corporation|Co|Company|Group|Services|Solutions|Technologies|Enterprises|Partners|Associates|Industries)\.?)$',
        # Pattern for company name after separator line (e.g., "----\nCompany Name")
        r'^([A-Z][A-Za-z0-9\s&,\.\-\']+(?:\'s)?\s+(?:Inc|LLC|Ltd|Corp|Corporation|Co|Company|Group|Services|Solutions|Technologies|Enterprises|Partners|Associates|Industries))$',
    ]

    # Search signature section
    lines = signature_text.split('\n')
    # Only check first 10 lines of signature and skip personal names
    for line in lines[:10]:
        line = line.strip()
        if not line or len(line) < 3:
            continue

        # Skip lines that look like personal names, contact info, or roles
        # But don't skip company names with corporate suffixes

        # Check if line contains corporate suffixes first
        corporate_suffixes = r'\b(?:Inc|LLC|Ltd|Corp|Corporation|Co|Company|Group|Services|Solutions|Technologies|Enterprises|Partners|Associates|Industries)\b'
        has_corporate_suffix = re.search(corporate_suffixes, line, re.IGNORECASE)

        if not has_corporate_suffix:
            # Only apply skip patterns if no corporate suffix found
            skip_patterns = [
                r'^[A-Z][a-z]+\s+[A-Z][a-z]+$',  # First Last name (but not if it has corporate suffix)
                r'^\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',  # Phone numbers
                r'^[A-Za-z\s]+(Manager|Director|CEO|CTO|CFO|President|VP|Engineer|Developer|Consultant)',  # Job titles
                r'@',  # Email addresses
                r'http',  # URLs
            ]

            should_skip = False
            for skip_pattern in skip_patterns:
                # Don't use IGNORECASE for skip patterns - we want precise matching
                if re.search(skip_pattern, line):
                    should_skip = True
                    break

            if should_skip:
                continue

        for pattern in company_patterns:
            match = re.search(pattern, line, re.MULTILINE)
            if match:
                company = match.group(1) if match.groups() else match.group(0)
                # Clean up
                company = company.strip()
                # Additional validation
                if (len(company) <= 50 and
                    len(company) >= 3 and
                    '@' not in company and
                    '://' not in company and
                    not company.lower().startswith('sent from')):
                    return company

    return ''


_REPLY_MARKER_PATTERNS = (
    # A line that starts with '>' (Gmail and most clients quote this way).
    r'(?:^|\n)[ \t]*>',
    # "On <date>, <person> wrote:" — Gmail/Apple Mail reply prelude.
    r'(?:^|\n)[ \t]*On .{1,200}\bwrote:[ \t]*(?:\n|$)',
    # Outlook classic divider.
    r'(?:^|\n)-{5,}[ \t]*Original Message[ \t]*-{5,}',
    # Outlook forward header — three header lines in a row.
    r'(?:^|\n)From:[ \t].+\nSent:[ \t].+\nTo:[ \t].+',
    # Apple Mail forward marker.
    r'(?:^|\n)Begin forwarded message:',
)

_REPLY_MARKER_RE = re.compile('|'.join(_REPLY_MARKER_PATTERNS), re.IGNORECASE)


def strip_quoted_reply(text):
    """Trim a plain-text email body at the first reply or forward marker.

    Recognizes Gmail-style ">" quote lines, "On <date>, <person> wrote:"
    preludes, Outlook's "-----Original Message-----" divider, Outlook
    forward header blocks (From:/Sent:/To: in three consecutive lines), and
    Apple Mail's "Begin forwarded message:" marker.

    Normalizes CRLF -> LF before matching. Returns the body up to (not
    including) the earliest marker, rstrip'd. If no marker matches, returns
    the input unchanged.
    """
    if not text:
        return ''
    normalized = text.replace('\r\n', '\n').replace('\r', '\n')
    match = _REPLY_MARKER_RE.search(normalized)
    if not match:
        return text
    return normalized[:match.start()].rstrip()


def extract_email_body(email_content, trim_signature=True):
    """
    Extract the most relevant body content from email.

    Prefers plain text, removes quoted replies via `strip_quoted_reply`.
    When `trim_signature` is True (default, for backwards compatibility),
    also strips any text following a broad set of signature markers —
    useful when the caller just wants a short excerpt. Callers that want
    the full body and intend to apply their own sign-off trim (e.g.
    `trim_body_at_signoff`) should pass `trim_signature=False`.

    Args:
        email_content (dict): Dict with 'text' and 'html' keys
        trim_signature (bool): If True, also cut at the first signature marker

    Returns:
        str: Cleaned email body
    """
    if not email_content:
        return ''

    # Prefer text over HTML
    body = email_content.get('text', '')
    if not body:
        # TODO: Could use html2text or similar to convert HTML
        body = email_content.get('html', '')

    if not body:
        return ''

    body = strip_quoted_reply(body)

    if trim_signature:
        # Broad signature trim — kept for the deprecated HTML view path.
        signature_patterns = [
            r'\n--\s*\n',
            r'\n\s*Best regards',
            r'\n\s*Sincerely',
            r'\n\s*Regards',
            r'\n\s*Thank you',
            r'\n\s*Thanks',
        ]

        for pattern in signature_patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                body = body[:match.start()]
                break

    return body.strip()


# Longest first so alternation prefers "Best regards," over "Best,".
_SIGNOFF_PHRASES = (
    'Best regards',
    'Kind regards',
    'Many thanks',
    'Thank you',
    'Thanks',
    'Thx',
    'Cheers',
    'Regards',
    'Sincerely',
    'Cordially',
    'Best',
)

_SIGNOFF_RE = re.compile(
    r'(?:^|\n)[ \t]*(?:'
    r'(?:' + '|'.join(_SIGNOFF_PHRASES) + r'),'      # signoff word + comma, OR
    r'|-{3,}'                                         # a separator line of 3+ hyphens
    r')[ \t]*\n[ \t]*\S',
    re.IGNORECASE,
)


def trim_body_at_signoff(body):
    """Trim an email body just before a single sign-off line + signer name.

    Only trims when we can identify the pattern:

        <signoff phrase>,
        <name on the next line>

    where the signoff is one of `_SIGNOFF_PHRASES`. Without the comma or the
    following name, the body is returned unchanged — we'd rather keep too much
    than throw real content away.
    """
    if not body:
        return ''
    # IMAP bodies routinely arrive with CRLF — normalize so the regex's
    # `\n[ \t]*` boundary works regardless of source line endings.
    normalized = body.replace('\r\n', '\n').replace('\r', '\n')
    match = _SIGNOFF_RE.search(normalized)
    if not match:
        return body
    return normalized[:match.start()].rstrip()


_SUBJECT_PREFIX_RE = re.compile(r'^\s*(?:(?:Re|Fwd?|FW)\s*:\s*)+', re.IGNORECASE)
_JOB_NAME_MAX = 50


def clean_subject_for_job_name(subject):
    """Strip leading Re:/Fwd: prefixes from an email subject and clamp to the
    50-char Job.name limit (with an ellipsis if it had to be truncated)."""
    if not subject:
        return ''
    cleaned = _SUBJECT_PREFIX_RE.sub('', subject).strip()
    if len(cleaned) > _JOB_NAME_MAX:
        cleaned = cleaned[:_JOB_NAME_MAX - 3] + '...'
    return cleaned
