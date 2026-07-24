"""Tests for the purge_qbo_data management command.

The command reads a dumpdata-format JSON file and writes a copy with every
QBO-company-scoped value stripped, so a dataset prepared against one sandbox
company can be pointed at another (e.g. prepping a staging seed). It never
touches a database. See docs/designs/quickbooks-integration.md.
"""
import json
import os
import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase


def record(model, pk, **fields):
    return {'model': model, 'pk': pk, 'fields': fields}


INPUT_RECORDS = [
    record('sessions.session', 'abc123', session_data='blob',
           expire_date='2026-07-19T20:05:38.497Z'),
    record('core.accountingcategory', 1, name='Service',
           qbo_item_id='11', qbo_expense_account_id='22'),
    record('core.configuration', 5, key='qbo_payment_accounts',
           value='[{"qbo_account_id": "42"}]'),
    record('core.configuration', 6, key='unrelated_key', value='keep-me'),
    record('invoicing.invoice', 10, job=3, invoice_number='INV-1',
           status='paid', qbo_id='301', qbo_payment_status='Paid',
           qbo_amount_paid='100.00'),
    record('purchasing.bill', 20, business=1, status='paid_in_full',
           qbo_id='401', qbo_payment_status='Paid'),
    record('contacts.business', 1, business_name='Acme',
           qbo_customer_id='51', qbo_vendor_id='52'),
    record('contacts.contact', 2, first_name='Jo', qbo_customer_id='61'),
    record('expenses.expense', 30, amount='25.00', payment_account_id='42',
           qbo_id='701', qbo_sync_status='synced', qbo_sync_error='',
           qbo_pending_op=''),
    record('expenses.reimbursement', 40, payment_account_id='42', qbo_id='',
           qbo_sync_status='sync_failed', qbo_sync_error='boom',
           qbo_pending_op='create'),
    record('purchasing.billpayment', 50, bill=20, amount='10.00',
           payment_account_id='42', qbo_id='801', qbo_sync_status='synced',
           qbo_sync_error='', qbo_pending_op=''),
    record('inventory.inventoryitem', 80, code='PLY', description='Plywood',
           qbo_id='77'),
    record('estimates.serviceitem', 90, template_name='CNC Cutting',
           qbo_id='78'),
    record('qbo.qboconnection', 60, realm_id='9130350000000000',
           access_token='tok', refresh_token='ref', is_active=True),
    record('qbo.qbosynclog', 70, entity_type='invoice', entity_id=10,
           qbo_entity_type='Invoice', qbo_entity_id='301',
           action='create', status='success'),
]


class PurgeQBODataTest(SimpleTestCase):
    """purge_qbo_data transforms a dumpdata JSON file into a purged copy."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.in_path = os.path.join(self.tmpdir.name, 'in.json')
        self.out_path = os.path.join(self.tmpdir.name, 'out.json')
        with open(self.in_path, 'w') as f:
            json.dump(INPUT_RECORDS, f)

    def purge(self):
        out = StringIO()
        call_command('purge_qbo_data', self.in_path, self.out_path,
                     stdout=out)
        with open(self.out_path) as f:
            result = json.load(f)
        by_model = {}
        for rec in result:
            by_model.setdefault(rec['model'], []).append(rec)
        return result, by_model, out.getvalue()

    def test_clears_catalog_item_mirror_ids(self):
        _, by_model, _ = self.purge()
        inv_fields = by_model['inventory.inventoryitem'][0]['fields']
        self.assertEqual(inv_fields['qbo_id'], '')
        svc_fields = by_model['estimates.serviceitem'][0]['fields']
        self.assertEqual(svc_fields['qbo_id'], '')

    def test_clears_accounting_category_mappings(self):
        _, by_model, _ = self.purge()
        fields = by_model['core.accountingcategory'][0]['fields']
        self.assertEqual(fields['qbo_item_id'], '')
        self.assertEqual(fields['qbo_expense_account_id'], '')
        self.assertEqual(fields['name'], 'Service')

    def test_drops_payment_accounts_config_and_keeps_other_keys(self):
        _, by_model, _ = self.purge()
        keys = [r['fields']['key'] for r in by_model['core.configuration']]
        self.assertEqual(keys, ['unrelated_key'])
        self.assertEqual(
            by_model['core.configuration'][0]['fields']['value'], 'keep-me')

    def test_clears_invoice_qbo_fields_but_not_status(self):
        _, by_model, _ = self.purge()
        fields = by_model['invoicing.invoice'][0]['fields']
        self.assertIsNone(fields['qbo_id'])
        self.assertEqual(fields['qbo_payment_status'], '')
        self.assertIsNone(fields['qbo_amount_paid'])
        self.assertEqual(fields['status'], 'paid')

    def test_leaves_retired_bill_rows_untouched(self):
        # Bill models are retired schema-only stubs; purge no longer manages
        # them — legacy dump rows pass through unchanged.
        _, by_model, _ = self.purge()
        fields = by_model['purchasing.bill'][0]['fields']
        self.assertEqual(fields['qbo_id'], '401')

    def test_clears_business_and_contact_ids(self):
        _, by_model, _ = self.purge()
        business = by_model['contacts.business'][0]['fields']
        self.assertIsNone(business['qbo_customer_id'])
        self.assertIsNone(business['qbo_vendor_id'])
        contact = by_model['contacts.contact'][0]['fields']
        self.assertIsNone(contact['qbo_customer_id'])

    def test_resets_syncable_records(self):
        _, by_model, _ = self.purge()
        for model in ('expenses.expense', 'expenses.reimbursement'):
            fields = by_model[model][0]['fields']
            self.assertEqual(fields['qbo_id'], '')
            self.assertEqual(fields['qbo_sync_status'], 'pending')
            self.assertEqual(fields['qbo_sync_error'], '')
            self.assertEqual(fields['qbo_pending_op'], '')

    def test_keeps_payment_account_id_values(self):
        # Dangling references to the purged account list are accepted; the
        # which-account information itself stays readable.
        _, by_model, _ = self.purge()
        for model in ('expenses.expense', 'expenses.reimbursement'):
            self.assertEqual(
                by_model[model][0]['fields']['payment_account_id'], '42')

    def test_drops_connection_and_sync_log_records(self):
        _, by_model, _ = self.purge()
        self.assertNotIn('qbo.qboconnection', by_model)
        self.assertNotIn('qbo.qbosynclog', by_model)

    def test_unrelated_records_pass_through_untouched_in_order(self):
        result, _, _ = self.purge()
        self.assertEqual(result[0], INPUT_RECORDS[0])
        expected_order = [r['model'] for r in INPUT_RECORDS
                          if r['model'] not in ('qbo.qboconnection',
                                                'qbo.qbosynclog')
                          and not (r['model'] == 'core.configuration'
                                   and r['fields']['key']
                                   == 'qbo_payment_accounts')]
        self.assertEqual([r['model'] for r in result], expected_order)

    def test_missing_qbo_models_are_fine(self):
        # A dump from before a QBO feature existed simply lacks those
        # records; the command must not choke on their absence.
        with open(self.in_path, 'w') as f:
            json.dump([record('jobs.job', 1, name='J')], f)
        result, _, _ = self.purge()
        self.assertEqual(result, [record('jobs.job', 1, name='J')])

    def test_in_place_when_input_and_output_are_same_path(self):
        call_command('purge_qbo_data', self.in_path, self.in_path,
                     stdout=StringIO())
        with open(self.in_path) as f:
            result = json.load(f)
        models = {r['model'] for r in result}
        self.assertNotIn('qbo.qboconnection', models)

    def test_reports_counts(self):
        _, _, output = self.purge()
        self.assertIn('scrubbed', output)
        self.assertIn('dropped', output)
