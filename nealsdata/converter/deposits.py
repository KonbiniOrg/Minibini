"""Deposit invoices and their deductions (design: docs/plans/2026-10-21-
converter-deposit-invoices-design.md; summary in convert.md §4 "Deposits").

FreeAgent has no deposit concept: a deposit is a separate single-line invoice
("Materials deposit for job 07445") and the final invoice later carries a
negative line ("Material Deposit (Inv 12345)"). Konbini models a deposit as a
line in a deposit accounting category on a paid invoice, deducted by a credit
line that claims it through an InvoiceLineItemSource row of type 'deposit'.

`plan_deposits` is the pure matcher: it decides which deposit invoices land on
which spine job and which deductions provably correspond to which deposit
line. `build.build_invoices` applies the plan at emission time.
"""
import re
from decimal import Decimal

from nealsdata.converter import parsing as P

KIND_DEPOSIT = 'deposit'          # a deposit charge line (DEP category)
KIND_CREDIT = 'deposit_credit'    # a deduction paired with a deposit line

_TOKEN_RE = re.compile(r'\d{4,}')


def mentions_deposit(description):
    return 'deposit' in (description or '').lower()


def line_amount(li_row):
    """qty × price of a sheet line row."""
    return P.parse_decimal(li_row.get('Quantity')) * P.parse_decimal(li_row.get('Price'))


def number_tokens(description):
    """[(int, zero_padded)] for every run of four or more digits.

    Job numbers in the export are zero-padded five digits, invoice references
    are unpadded, and their ranges overlap — the leading zero is the one
    signal that tells them apart. Shorter runs (dates, revision suffixes)
    never count.
    """
    return [(int(t), t.startswith('0')) for t in _TOKEN_RE.findall(description or '')]


class DepositPlan:
    def __init__(self):
        self.deposit_invoices = set()   # refs of invoices with a deposit charge line
        self.placed = {}                # ref -> base_ref (deposit invoices on a spine job)
        self.deposit_lines = set()      # (ref, line_idx) deposit charge lines
        self.credits = {}               # (final_ref, idx) -> (dep_ref, dep_idx)
        self.plain = set()              # (ref, idx) unpaired deductions on placed invoices
        self.counts = {'placed': 0, 'paired': 0, 'standalone': 0,
                       'skipped': 0, 'plain': 0}


def _ref(container):
    return str(container.get('Reference') or '').strip()


def ref_number(ref):
    m = re.match(r'(\d+)', ref)
    return int(m.group(1)) if m else None


def _sort_key(container):
    return (P.to_datetime(container.get('Date')) or P.to_datetime('1970-01-01'),
            _ref(container))


def plan_deposits(pairs, spine_numbers, est_link, status_of):
    """Decide placements and pairings.

    pairs:         [(container_row, [line_rows])] in sheet order
    spine_numbers: {int(job number): base_ref} for every spine job
    est_link:      {invoice ref: base_ref} — the Estimates sheet's
                   `Invoice Reference` linkage (today's only linkage)
    status_of:     container_row -> mapped app status ('paid', 'open', ...)
    """
    plan = DepositPlan()
    by_ref = {}
    dep_lines_by_ref = {}
    for container, lis in pairs:
        ref = _ref(container)
        by_ref[ref] = (container, lis)
        idxs = [i for i, li in enumerate(lis)
                if mentions_deposit(li.get('Description')) and line_amount(li) > 0]
        if idxs:
            dep_lines_by_ref[ref] = idxs
            plan.deposit_invoices.add(ref)
            plan.deposit_lines.update((ref, i) for i in idxs)
    dep_number_to_ref = {ref_number(r): r for r in dep_lines_by_ref
                         if ref_number(r) is not None}

    def job_tokens(description, allow_invoice):
        """Spine base_refs named by a description; a token that resolves to
        nothing is noise. `allow_invoice` is the deduction-side reading: an
        unpadded token names a deposit invoice first, a job second."""
        jobs, invoices = [], []
        for n, padded in number_tokens(description):
            if not padded and allow_invoice and n in dep_number_to_ref:
                invoices.append(dep_number_to_ref[n])
            elif n in spine_numbers:
                jobs.append(spine_numbers[n])
        return jobs, invoices

    # --- §4.2 rules 1–2: estimate link, then the deposit line's job token ---
    ambiguous = set()
    for ref, idxs in dep_lines_by_ref.items():
        if ref in est_link:
            plan.placed[ref] = est_link[ref]
            continue
        container, lis = by_ref[ref]
        named = set()
        for i in idxs:
            jobs, _ = job_tokens(lis[i].get('Description'), allow_invoice=False)
            named.update(jobs)
        if len(named) == 1:
            plan.placed[ref] = named.pop()
        elif named:
            ambiguous.add(ref)

    # --- §4.3 pairing, with §4.2 rule 3 placement by the deduction ---------
    paired_lines = set()
    placed_invoices = sorted(
        (by_ref[r] for r in by_ref if r in est_link or r in plan.placed),
        key=lambda cl: _sort_key(cl[0]))
    # A deposit invoice placed by rule 3 may itself carry deductions in
    # theory; walking a snapshot keeps the pass single and deterministic.
    for container, lis in placed_invoices:
        ref = _ref(container)
        job = est_link.get(ref) or plan.placed.get(ref)
        final_cancelled = status_of(container) == 'cancelled'
        for idx, li in enumerate(lis):
            desc = li.get('Description')
            if not mentions_deposit(desc) or line_amount(li) >= 0:
                continue
            if final_cancelled:
                plan.plain.add((ref, idx))
                continue
            ded_jobs, ded_invoices = job_tokens(desc, allow_invoice=True)
            if ded_invoices:
                candidates = [by_ref[r] for r in dict.fromkeys(ded_invoices)]
            else:
                candidates = sorted(
                    (by_ref[r] for r, b in plan.placed.items()
                     if b == job and r not in ambiguous),
                    key=lambda cl: _sort_key(cl[0]))
            match = _find_match(candidates, li, job, ded_jobs, ded_invoices,
                                dep_lines_by_ref, plan, ambiguous, paired_lines,
                                status_of, job_tokens)
            if match is None:
                plan.plain.add((ref, idx))
                continue
            dep_ref, dep_idx = match
            plan.credits[(ref, idx)] = match
            paired_lines.add(match)
            plan.placed.setdefault(dep_ref, job)   # rule 3

    paired_refs = {dep_ref for dep_ref, _ in plan.credits.values()}
    plan.counts['placed'] = len(plan.placed)
    plan.counts['paired'] = len(paired_refs)
    plan.counts['standalone'] = len(plan.placed) - len(paired_refs)
    plan.counts['skipped'] = len(dep_lines_by_ref) - len(plan.placed)
    plan.counts['plain'] = len(plan.plain)
    return plan


def _find_match(candidates, ded_li, job, ded_jobs, ded_invoices,
                dep_lines_by_ref, plan, ambiguous, paired_lines,
                status_of, job_tokens):
    """First (dep_ref, dep_idx) that passes every present test, else None."""
    owed = -line_amount(ded_li)
    for dep_container, dep_lis in candidates:
        dep_ref = _ref(dep_container)
        if dep_ref in ambiguous or status_of(dep_container) != 'paid':
            continue
        placed_on = plan.placed.get(dep_ref)
        if placed_on is not None and placed_on != job:
            continue
        if ded_invoices and dep_ref not in ded_invoices:
            continue
        if any(j != job for j in ded_jobs):
            continue
        sheet_amounts = {P.parse_decimal(dep_container.get('Net Amount')),
                         P.parse_decimal(dep_container.get('Total Value'))}
        for dep_idx in dep_lines_by_ref.get(dep_ref, []):
            if (dep_ref, dep_idx) in paired_lines:
                continue
            dep_li = dep_lis[dep_idx]
            dep_jobs, _ = job_tokens(dep_li.get('Description'), allow_invoice=False)
            if any(j != job for j in dep_jobs):
                continue
            amounts = {line_amount(dep_li)} | sheet_amounts
            if owed.quantize(Decimal('0.01')) not in {
                    a.quantize(Decimal('0.01')) for a in amounts}:
                continue
            return (dep_ref, dep_idx)
    return None
