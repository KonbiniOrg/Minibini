"""Pure parsing/normalisation helpers for the Neal's data converter."""
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation


def parse_decimal(value):
    if value is None or value == '':
        return Decimal('0')
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    cleaned = re.sub(r'[^0-9.\-]', '', str(value))
    try:
        return Decimal(cleaned) if cleaned else Decimal('0')
    except InvalidOperation:
        return Decimal('0')


def format_date(value):
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d')
    text = str(value).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(text, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None


def format_datetime(value):
    """Like format_date, but returns a timezone-aware (UTC midnight) string
    suitable for a Django DateTimeField under USE_TZ=True. None -> None."""
    d = format_date(value)
    return f'{d}T00:00:00+00:00' if d else None


def to_datetime(value):
    """Parse a cell into a datetime, or None."""
    if isinstance(value, datetime):
        return value
    if value in (None, ''):
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
    return None


def split_name(full_name):
    if not full_name or not str(full_name).strip():
        return ('(unknown)', '(unknown)')
    parts = str(full_name).strip().split()
    if len(parts) == 1:
        return (parts[0], '(unknown)')
    return (parts[0], ' '.join(parts[1:]))


def revision_parts(reference):
    """('03024b') -> ('03024', 1). Suffix letters a/b/c... -> version index."""
    m = re.match(r'^(\d+)([a-zA-Z]*)$', str(reference).strip())
    if not m:
        return (str(reference).strip(), 0)
    digits, suffix = m.group(1), m.group(2).lower()
    if not suffix:
        return (digits, 0)
    return (digits, ord(suffix[-1]) - ord('a'))


def base_reference(reference):
    """Leading run of digits of a document reference, used as the join key
    between Kanban External IDs and FreeAgent Estimate References.
    '03077-SOLID' -> '03077', '03024b' -> '03024', '07754' -> '07754'.
    Falls back to the stripped string when there are no leading digits."""
    text = str(reference).strip()
    m = re.match(r'(\d+)', text)
    return m.group(1) if m else text


def hours_to_duration(value):
    """'1.5' hours -> Django DurationField string '01:30:00'. '' -> None."""
    if value in (None, ''):
        return None
    try:
        hours = float(value)
    except (TypeError, ValueError):
        return None
    total = timedelta(hours=hours)
    s = int(total.total_seconds())
    return f'{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}'


def parse_kanban_name(name):
    """'Business (Contact)' -> ('Business', 'Contact'); 'Business' -> ('Business', None)."""
    m = re.match(r'^(.*?)\s*\(([^)]+)\)\s*$', str(name).strip())
    if m:
        return (m.group(1).strip(), m.group(2).strip())
    return (str(name).strip(), None)


MATERIAL_KEYWORDS = (
    'plywood', 'acrylic', 'mdf', 'sheet', 'hardwood', 'melamine', 'sintra',
    'aluminum', 'aluminium', 'board feet', 'lumber', 'plastic', 'steel',
    'wood', 'foam', 'gator', 'laminate', 'trupan', 'chipboard', 'baltic birch',
)
COUNT_UNITS = ('each', 'ea', 'pcs', 'pieces', 'unit', 'units')


def classify_line_item(item_type, description):
    """Return one of: 'skip', 'task', 'material', 'lineitem'."""
    it = (item_type or '').strip().lower()
    if it == 'comment':
        return 'skip'
    if it in ('discount', 'credit'):
        return 'lineitem'
    # A line item describing a cut operation is always labour, never a
    # material — even if its Item Type or keywords would say otherwise.
    if (description or '').strip().lower().startswith('cut'):
        return 'task'
    if it in ('hours', 'days', 'services'):
        return 'task'
    if it in ('products', 'expenses'):
        return 'material'
    # '-no unit-' and anything unrecognised: keyword heuristic
    desc = (description or '').lower()
    if any(kw in desc for kw in MATERIAL_KEYWORDS):
        return 'material'
    return 'task'


def parse_checklist(cell):
    """Parse a Kanban 'Checklist' cell into ordered task entries.

    Each non-blank line looks like '[ ] text' (unchecked) or '[X] text'
    (checked). A line with leading whitespace is a subtask of the most
    recent non-indented line. Lines may carry a trailing ';'.
    Returns a list of dicts: {'text': str, 'completed': bool,
    'is_subtask': bool}.
    """
    items = []
    for raw in (cell or '').splitlines():
        if not raw.strip():
            continue
        is_subtask = raw[:1] in (' ', '\t')
        line = raw.strip().rstrip(';').strip()
        m = re.match(r'^\[\s*([xX]?)\s*\]\s*(.*)$', line)
        if not m:
            continue
        text = m.group(2).strip().rstrip(';').strip()
        if not text:
            continue
        items.append({
            'text': text,
            'completed': bool(m.group(1)),
            'is_subtask': is_subtask,
        })
    return items


def checklist_scheme_name(task_name):
    """RateScheme name for a task, chosen by keyword in its name.

    Starts with 'cut' -> 'CNC routing'; contains 'laser' -> 'Laser';
    contains 'draw'/'cad'/'model' -> 'CAD'; otherwise -> 'Shop labor'.
    """
    n = (task_name or '').strip().lower()
    if n.startswith('cut'):
        return 'CNC routing'
    if 'laser' in n:
        return 'Laser'
    if 'draw' in n or 'cad' in n or 'model' in n:
        return 'CAD'
    return 'Shop labor'


def infer_algorithm(item_type, units):
    """RateScheme.algorithm for a Task-classified line item."""
    it = (item_type or '').strip().lower()
    u = (units or '').strip().lower()
    if it in ('hours', 'days') or u in ('hour', 'hours', 'day', 'days'):
        return 'elapsed_time'
    if u in COUNT_UNITS:
        return 'entered_qty'
    return 'flat_fee'
