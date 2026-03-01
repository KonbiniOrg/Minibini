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


def extract_email_body(email_content):
    """
    Extract the most relevant body content from email.

    Prefers plain text, removes signatures and quoted replies.

    Args:
        email_content (dict): Dict with 'text' and 'html' keys

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

    # Remove quoted replies (lines starting with >)
    lines = body.split('\n')
    cleaned_lines = []
    for line in lines:
        if line.strip().startswith('>'):
            break  # Stop at quoted content
        cleaned_lines.append(line)

    body = '\n'.join(cleaned_lines)

    # Truncate signature (common patterns)
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
