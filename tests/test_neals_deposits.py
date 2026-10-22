# tests/test_neals_deposits.py
"""Converter deposit translation (docs/plans/2026-10-21-converter-deposit-
invoices-design.md): FreeAgent deposit invoices land on their spine jobs and
deduction lines that provably correspond become the app's credit shape."""
import unittest
from decimal import Decimal

from nealsdata.converter import build
from nealsdata.converter import deposits as D
from nealsdata.converter.orchestrator import NealsDataConverter


def _inv(ref, date='2026-03-01', status='Sent', paid='2026-03-10',
         net=None, total=None):
    return {'Reference': ref, 'Date': date, 'Status': status,
            'Paid Date': paid, 'Net Amount': net, 'Total Value': total,
            'Projects': ''}


def _li(desc, qty='1', price='0', item_type="'-no unit-"):
    return {'Reference': '', 'Item Type': item_type, 'Quantity': qty,
            'Price': price, 'Description': desc}


def _status(container):
    return build._map_invoice_status(container.get('Status'),
                                     container.get('Paid Date'))


SPINE = {7445: '07445', 7500: '07500'}


def _plan(pairs, est_link=None, spine=SPINE):
    return D.plan_deposits(pairs, spine, est_link or {}, _status)


class NumberTokenTest(unittest.TestCase):
    def test_four_plus_digit_runs_with_padding_flag(self):
        self.assertEqual(D.number_tokens('Materials deposit for 07459-R2 PAID 9/16/25'),
                         [(7459, True)])
        self.assertEqual(D.number_tokens('Material Deposit (Inv#8831)'),
                         [(8831, False)])
        self.assertEqual(D.number_tokens('Materials deposit received 2-18-2016'),
                         [(2016, False)])
        self.assertEqual(D.number_tokens('Deposit'), [])


class PlacementTest(unittest.TestCase):
    def test_job_token_places_deposit_invoice(self):
        pairs = [(_inv('9001'), [_li('Materials deposit for job 07445', '1', '500')])]
        plan = _plan(pairs)
        self.assertEqual(plan.placed, {'9001': '07445'})
        self.assertEqual(plan.deposit_lines, {('9001', 0)})
        self.assertEqual(plan.counts['standalone'], 1)

    def test_loose_unpadded_job_number_places(self):
        pairs = [(_inv('9001'), [_li('Materials deposit 7445', '1', '500')])]
        self.assertEqual(_plan(pairs).placed, {'9001': '07445'})

    def test_estimate_link_beats_job_token(self):
        pairs = [(_inv('9001'), [_li('Materials deposit for job 07445', '1', '500')])]
        plan = _plan(pairs, est_link={'9001': '07500'})
        self.assertEqual(plan.placed, {'9001': '07500'})

    def test_non_spine_job_is_skipped(self):
        pairs = [(_inv('9001'), [_li('Materials deposit for job 03006', '1', '500')])]
        plan = _plan(pairs)
        self.assertEqual(plan.placed, {})
        self.assertEqual(plan.counts['skipped'], 1)

    def test_two_distinct_job_tokens_is_ambiguous(self):
        pairs = [(_inv('9001'), [_li('Materials deposit 07445 and 07500', '1', '500')])]
        plan = _plan(pairs)
        self.assertEqual(plan.placed, {})
        self.assertEqual(plan.counts['skipped'], 1)

    def test_noise_tokens_are_ignored(self):
        pairs = [(_inv('9001'), [_li('Materials deposit 07445 - 2091 Google', '1', '500')])]
        self.assertEqual(_plan(pairs).placed, {'9001': '07445'})

    def test_padded_token_never_names_an_invoice(self):
        # Deposit invoice 7445 exists AND job 07445 is in the spine; a padded
        # token on a deduction is the job, so the invoice test is absent.
        dep = (_inv('7445', date='2026-02-01'), [_li('Materials deposit', '1', '500')])
        other = (_inv('9001', date='2026-02-02'), [_li('Materials deposit for 07445', '1', '500')])
        final = (_inv('9100', date='2026-03-01'),
                 [_li('cutting', '1', '1000'),
                  _li('Materials deposit 07445 PAID 5/8/25', '1', '-500')])
        plan = _plan([dep, other, final], est_link={'9100': '07445'})
        # 7445 unplaced (no job token); 9001 placed by job; deduction pairs 9001
        self.assertEqual(plan.placed, {'9001': '07445'})
        self.assertEqual(plan.credits, {('9100', 1): ('9001', 0)})

    def test_deposit_without_number_is_placed_by_its_deduction(self):
        dep = (_inv('9001'), [_li('Materials deposit', '1', '500')])
        final = (_inv('9100'), [_li('cutting', '1', '1000'),
                                _li('Material Deposit (Inv 9001)', '1', '-500')])
        plan = _plan([dep, final], est_link={'9100': '07445'})
        self.assertEqual(plan.placed, {'9001': '07445'})
        self.assertEqual(plan.credits, {('9100', 1): ('9001', 0)})
        self.assertEqual(plan.counts, {'placed': 1, 'paired': 1, 'standalone': 0,
                                       'skipped': 0, 'plain': 0})


class PairingTest(unittest.TestCase):
    def _case(self, dep_desc='Materials deposit for job 07445', dep_amt='500',
              ded_desc='Material Deposit (Inv 9001)', ded_amt='-500',
              dep_status='Sent', dep_paid='2026-03-10', final_status='Sent',
              final_job='07445', net=None, total=None):
        dep = (_inv('9001', status=dep_status, paid=dep_paid, net=net, total=total),
               [_li(dep_desc, '1', dep_amt)])
        final = (_inv('9100', status=final_status),
                 [_li('cutting', '1', '1000'), _li(ded_desc, '1', ded_amt)])
        return _plan([dep, final], est_link={'9100': final_job})

    def test_all_three_numbers_agree(self):
        plan = self._case()
        self.assertEqual(plan.credits, {('9100', 1): ('9001', 0)})
        self.assertEqual(plan.plain, set())
        self.assertEqual(plan.counts['paired'], 1)

    def test_missing_invoice_number_pairs_on_job_and_amount(self):
        plan = self._case(ded_desc='Materials deposit paid')
        self.assertEqual(plan.credits, {('9100', 1): ('9001', 0)})

    def test_missing_job_number_pairs_on_invoice_and_amount(self):
        plan = self._case(dep_desc='Materials deposit')
        self.assertEqual(plan.credits, {('9100', 1): ('9001', 0)})

    def test_wrong_invoice_number_refuses(self):
        extra = (_inv('9002'), [_li('Materials deposit for job 07500', '1', '500')])
        dep = (_inv('9001'), [_li('Materials deposit for job 07445', '1', '500')])
        final = (_inv('9100'), [_li('cutting', '1', '1000'),
                                _li('Material Deposit (Inv 9002)', '1', '-500')])
        plan = _plan([extra, dep, final], est_link={'9100': '07445'})
        self.assertEqual(plan.credits, {})
        self.assertEqual(plan.plain, {('9100', 1)})
        self.assertEqual(plan.counts['plain'], 1)

    def test_wrong_amount_refuses(self):
        plan = self._case(ded_amt='-450')
        self.assertEqual(plan.credits, {})
        self.assertEqual(plan.plain, {('9100', 1)})

    def test_amount_may_match_sheet_net_or_total(self):
        plan = self._case(dep_amt='480', net='480', total='500')
        self.assertEqual(plan.credits, {('9100', 1): ('9001', 0)})

    def test_wrong_job_refuses(self):
        plan = self._case(dep_desc='Materials deposit for job 07500')
        self.assertEqual(plan.credits, {})
        self.assertEqual(plan.placed, {'9001': '07500'})   # still a standalone deposit there

    def test_unpaid_deposit_refuses(self):
        plan = self._case(dep_paid=None)
        self.assertEqual(plan.credits, {})
        self.assertEqual(plan.placed, {'9001': '07445'})

    def test_cancelled_final_never_pairs(self):
        plan = self._case(final_status='Cancelled')
        self.assertEqual(plan.credits, {})
        self.assertEqual(plan.plain, {('9100', 1)})

    def test_draft_final_may_pair(self):
        plan = self._case(final_status='Draft')
        self.assertEqual(plan.credits, {('9100', 1): ('9001', 0)})

    def test_deposit_line_pairs_once(self):
        dep = (_inv('9001', date='2026-01-01'), [_li('Materials deposit 07445', '1', '500')])
        f1 = (_inv('9100', date='2026-02-01'), [_li('Material Deposit (Inv 9001)', '1', '-500')])
        f2 = (_inv('9101', date='2026-03-01'), [_li('Material Deposit (Inv 9001)', '1', '-500')])
        plan = _plan([dep, f1, f2], est_link={'9100': '07445', '9101': '07445'})
        self.assertEqual(plan.credits, {('9100', 0): ('9001', 0)})
        self.assertEqual(plan.plain, {('9101', 0)})

    def test_two_deposit_lines_satisfy_two_deductions(self):
        dep = (_inv('9001'), [_li('Materials deposit 07445', '1', '500'),
                              _li('Hardware deposit 07445', '1', '200')])
        final = (_inv('9100'), [_li('Material Deposit (Inv 9001)', '1', '-200'),
                                _li('Material Deposit (Inv 9001)', '1', '-500')])
        plan = _plan([dep, final], est_link={'9100': '07445'})
        self.assertEqual(plan.credits, {('9100', 0): ('9001', 1), ('9100', 1): ('9001', 0)})

    def test_unnamed_deduction_prefers_earliest_deposit(self):
        d2 = (_inv('9002', date='2026-02-01'), [_li('Materials deposit 07445', '1', '500')])
        d1 = (_inv('9001', date='2026-01-01'), [_li('Materials deposit 07445', '1', '500')])
        final = (_inv('9100', date='2026-03-01'), [_li('Materials deposit paid', '1', '-500')])
        plan = _plan([d2, d1, final], est_link={'9100': '07445'})
        self.assertEqual(plan.credits, {('9100', 0): ('9001', 0)})

    def test_deduction_on_unplaced_invoice_is_not_considered(self):
        dep = (_inv('9001'), [_li('Materials deposit 07445', '1', '500')])
        final = (_inv('9100'), [_li('Material Deposit (Inv 9001)', '1', '-500')])
        plan = _plan([dep, final])          # 9100 not linked to any spine job
        self.assertEqual(plan.credits, {})
        self.assertEqual(plan.plain, set())
        self.assertEqual(plan.counts['standalone'], 1)


class EmissionTest(unittest.TestCase):
    """build_invoices applies the plan: DEP lines, credit shape, claim rows,
    plain deductions, and the force-to-draft exemption."""

    def _converter(self, rows, cards=None):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        c.loader.sheets_data = {'Invoices': rows}
        c.ac_by_code = {'SVC': 1, 'MTL': 2, 'PRD': 3, 'DLV': 4, 'DEP': 5}
        c.ac_svc_pk, c.ac_mat_pk = 1, 2
        c.jobs = {
            '07445': {'job_pk': 1, 'card': (cards or {}).get('07445', {}),
                      'estimate_rows': [{'Invoice Reference': '9100'}]},
            '07500': {'job_pk': 2, 'card': (cards or {}).get('07500', {}),
                      'estimate_rows': []},
        }
        return c

    @staticmethod
    def _rows(*pairs):
        rows = []
        for container, lis in pairs:
            rows.append(container)
            rows.extend(lis)
        return rows

    def _by_number(self, c):
        return {f['fields']['invoice_number']: f for f in c.fixture_data
                if f['model'] == 'invoicing.invoice'}

    def _lines(self, c, inv_pk):
        return sorted((f for f in c.fixture_data
                       if f['model'] == 'invoicing.invoicelineitem'
                       and f['fields']['invoice'] == inv_pk),
                      key=lambda f: f['fields']['line_number'])

    def _sources(self, c):
        return [f for f in c.fixture_data
                if f['model'] == 'invoicing.invoicelineitemsource']

    def test_pair_emits_deposit_invoice_credit_and_claim(self):
        rows = self._rows(
            (_inv('9001'), [_li('Materials deposit for job 07445', '1', '500')]),
            (_inv('9100'), [_li('cutting', '2', '300'),
                            _li('Material Deposit (Inv 9001)', '1', '-500')]))
        c = self._converter(rows)
        build.build_invoices(c)
        invs = self._by_number(c)
        self.assertEqual(set(invs), {'9001', '9100'})
        dep = invs['9001']
        self.assertEqual(dep['fields']['job'], 1)
        self.assertEqual(dep['fields']['status'], 'paid')
        [dep_line] = self._lines(c, dep['pk'])
        self.assertEqual(dep_line['fields']['accounting_category'], 5)
        self.assertEqual(c.invoice_line_kinds[dep_line['pk']], 'deposit')
        work, credit = self._lines(c, invs['9100']['pk'])
        self.assertEqual(c.invoice_line_kinds[work['pk']], 'task')
        self.assertEqual(credit['fields']['qty'], '1.00')
        self.assertEqual(credit['fields']['price'], '-500.00')
        self.assertEqual(credit['fields']['accounting_category'], 5)
        self.assertEqual(credit['fields']['description'], 'Material Deposit (Inv 9001)')
        self.assertEqual(c.invoice_line_kinds[credit['pk']], 'deposit_credit')
        [src] = self._sources(c)
        self.assertEqual(src['fields'], {'invoice_line_item': credit['pk'],
                                         'source_type': 'deposit',
                                         'source_pk': dep_line['pk']})
        self.assertEqual(c.deposit_summary['paired'], 1)

    def test_credit_price_is_negated_deposit_total_even_when_freeagent_differs_in_shape(self):
        rows = self._rows(
            (_inv('9001'), [_li('Materials deposit for job 07445', '2', '250')]),
            (_inv('9100'), [_li('Material Deposit (Inv 9001)', '-1', '500')]))
        c = self._converter(rows)
        build.build_invoices(c)
        [credit] = self._lines(c, self._by_number(c)['9100']['pk'])
        self.assertEqual((credit['fields']['qty'], credit['fields']['price']),
                         ('1.00', '-500.00'))

    def test_unpaired_deduction_is_plain_svc_lineitem(self):
        rows = self._rows(
            (_inv('9100'), [_li('cutting', '2', '300'),
                            _li('Material Deposit (Inv 9001)', '1', '-500')]))
        c = self._converter(rows)
        build.build_invoices(c)
        work, ded = self._lines(c, self._by_number(c)['9100']['pk'])
        self.assertEqual(ded['fields']['accounting_category'], 1)
        self.assertEqual((ded['fields']['qty'], ded['fields']['price']), ('1.00', '-500.00'))
        self.assertEqual(c.invoice_line_kinds[ded['pk']], 'lineitem')
        self.assertEqual(self._sources(c), [])
        self.assertEqual(c.deposit_summary['plain'], 1)

    def test_standalone_deposit_keeps_freeagent_status(self):
        rows = self._rows(
            (_inv('9001', paid=None), [_li('Materials deposit for job 07500', '1', '500')]))
        c = self._converter(rows)
        build.build_invoices(c)
        dep = self._by_number(c)['9001']
        self.assertEqual(dep['fields']['job'], 2)
        self.assertEqual(dep['fields']['status'], 'open')
        self.assertEqual(c.deposit_summary['standalone'], 1)

    def test_unplaceable_deposit_invoice_is_not_emitted(self):
        rows = self._rows(
            (_inv('9001'), [_li('Materials deposit for job 03006', '1', '500')]))
        c = self._converter(rows)
        build.build_invoices(c)
        self.assertEqual(self._by_number(c), {})
        self.assertEqual(c.deposit_summary['skipped'], 1)

    def test_deposit_invoice_exempt_from_force_to_draft(self):
        card = {'Stage': 'Invoice', 'Swimlane': "Neal's do"}
        rows = self._rows(
            (_inv('9001'), [_li('Materials deposit for job 07445', '1', '500')]),
            (_inv('9100'), [_li('cutting', '2', '300'),
                            _li('Material Deposit (Inv 9001)', '1', '-500')]))
        c = self._converter(rows, cards={'07445': card})
        self.assertTrue(build._is_neals_swimlane(card))
        build.build_invoices(c)
        invs = self._by_number(c)
        self.assertEqual(invs['9001']['fields']['status'], 'paid')
        self.assertEqual(invs['9100']['fields']['status'], 'draft')
        self.assertEqual(len(self._sources(c)), 1)   # drafted final still holds its claim

    def test_source_wiring_pass_leaves_deposit_kinds_alone(self):
        rows = self._rows(
            (_inv('9001'), [_li('Materials deposit for job 07445', '1', '500')]),
            (_inv('9100'), [_li('Material Deposit (Inv 9001)', '1', '-500')]))
        c = self._converter(rows)
        build.build_invoices(c)
        c.add_fixture('jobs.task', 1, {'job': 1, 'name': 'cut', 'status': 'complete'})
        build.build_invoice_line_item_sources(c)
        self.assertEqual([s['fields']['source_type'] for s in self._sources(c)],
                         ['deposit'])


class ArchiveDropsClaimsTest(unittest.TestCase):
    def test_archive_drops_invoice_claim_rows_and_keeps_credit_shape(self):
        from datetime import datetime, timezone
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        c.add_fixture('jobs.job', 1, {'status': 'completed',
                                      'completed_date': '2020-01-01T00:00:00+00:00',
                                      'project_manager': None})
        c.add_fixture('jobs.job', 2, {'status': 'completed',
                                      'completed_date': '2020-01-01T00:00:00+00:00',
                                      'project_manager': None})
        c.add_fixture('invoicing.invoice', 1, {'job': 1, 'status': 'paid'})
        c.add_fixture('invoicing.invoice', 2, {'job': 1, 'status': 'paid'})
        c.add_fixture('invoicing.invoice', 3, {'job': 2, 'status': 'paid'})
        c.add_fixture('invoicing.invoicelineitem', 1, {'invoice': 1, 'qty': '1.00',
                                                       'price': '500.00', 'accounting_category': 5})
        c.add_fixture('invoicing.invoicelineitem', 2, {'invoice': 2, 'qty': '1.00',
                                                       'price': '-500.00', 'accounting_category': 5})
        c.add_fixture('invoicing.invoicelineitem', 3, {'invoice': 3, 'qty': '1.00',
                                                       'price': '10.00', 'accounting_category': 1})
        c.add_fixture('invoicing.invoicelineitemsource', 1, {
            'invoice_line_item': 2, 'source_type': 'deposit', 'source_pk': 1})
        c.add_fixture('invoicing.invoicelineitemsource', 2, {
            'invoice_line_item': 3, 'source_type': 'task', 'source_pk': 9})
        # Only job 1 is old enough to archive.
        c.fixture_data[1]['fields']['completed_date'] = '2026-10-01T00:00:00+00:00'
        build.archive_old_jobs(c, build.archive_cutoff(datetime(2026, 10, 21, tzinfo=timezone.utc)))
        self.assertEqual(c.archived_job_pks, {1})
        srcs = [f for f in c.fixture_data if f['model'] == 'invoicing.invoicelineitemsource']
        self.assertEqual([s['pk'] for s in srcs], [2])
        credit = next(f for f in c.fixture_data
                      if f['model'] == 'invoicing.invoicelineitem' and f['pk'] == 2)
        self.assertEqual(credit['fields'], {'invoice': 2, 'qty': '1.00',
                                            'price': '-500.00', 'accounting_category': 5})


if __name__ == '__main__':
    unittest.main()
