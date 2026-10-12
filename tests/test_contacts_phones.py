# tests/test_contacts_phones.py
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import (
    Business, Contact, clean_phones, phones_digits_for, strip_phone,
)


class StripPhoneTest(TestCase):
    def test_strips_spaces_dashes_dots_parens_plus(self):
        self.assertEqual(strip_phone('+1 (555) 123-45.67'), '15551234567')

    def test_keeps_letters_so_extensions_match_as_typed(self):
        self.assertEqual(strip_phone('555-1234 x12'), '5551234x12')

    def test_none_is_empty(self):
        self.assertEqual(strip_phone(None), '')


class CleanPhonesTest(TestCase):
    def test_empty_and_none_become_empty_list(self):
        self.assertEqual(clean_phones(None), [])
        self.assertEqual(clean_phones([]), [])
        self.assertEqual(clean_phones(''), [])

    def test_normalizes_entries_and_drops_unknown_keys(self):
        out = clean_phones([{'number': ' 555-0100 ', 'label': ' cell ', 'x': 1},
                            {'number': '555-0200'}])
        self.assertEqual(out, [{'number': '555-0100', 'label': 'cell'},
                               {'number': '555-0200', 'label': ''}])

    def test_coerces_non_string_number(self):
        self.assertEqual(clean_phones([{'number': 5550100}]),
                         [{'number': '5550100', 'label': ''}])

    def test_rejects_non_list(self):
        with self.assertRaises(ValidationError) as cm:
            clean_phones({'number': '1'})
        self.assertIn('phones', cm.exception.message_dict)

    def test_rejects_entry_without_number(self):
        with self.assertRaises(ValidationError) as cm:
            clean_phones([{'label': 'cell'}])
        self.assertIn('Phone entry 1 needs a number.', cm.exception.message_dict['phones'][0])

    def test_rejects_non_dict_entry(self):
        with self.assertRaises(ValidationError):
            clean_phones(['555-0100'])

    def test_rejects_over_50_chars(self):
        with self.assertRaises(ValidationError):
            clean_phones([{'number': '5' * 51}])

    def test_digits_join(self):
        self.assertEqual(
            phones_digits_for([{'number': '(555) 123-4567', 'label': ''},
                               {'number': '555-9999 x12', 'label': 'work'}]),
            '5551234567 5559999x12')


class ContactPhonesModelTest(TestCase):
    def test_contact_with_no_phones_is_valid(self):
        c = Contact(first_name='A', last_name='B', email='a@b.test')
        c.full_clean()  # no "at least one phone" error any more
        c.save()
        self.assertEqual(c.phones, [])
        self.assertEqual(c.phone(), '')
        self.assertEqual(c.phones_digits, '')
        self.assertTrue(c.is_active)

    def test_save_normalizes_phones_and_maintains_digits(self):
        c = Contact.objects.create(first_name='A', last_name='B', email='a2@b.test',
                                   phones=[{'number': ' (555) 010-0 ', 'label': 'cell'}])
        c.refresh_from_db()
        self.assertEqual(c.phones, [{'number': '(555) 010-0', 'label': 'cell'}])
        self.assertEqual(c.phones_digits, '5550100')
        self.assertEqual(c.phone(), '(555) 010-0')

    def test_first_entry_is_primary(self):
        c = Contact(first_name='A', last_name='B', email='a3@b.test',
                    phones=[{'number': '1', 'label': 'home'}, {'number': '2', 'label': 'cell'}])
        self.assertEqual(c.phone(), '1')

    def test_full_clean_reports_phones_field_error(self):
        c = Contact(first_name='A', last_name='B', email='a4@b.test', phones=[{'label': 'x'}])
        with self.assertRaises(ValidationError) as cm:
            c.full_clean()
        self.assertIn('phones', cm.exception.message_dict)


class BusinessPhonesModelTest(TestCase):
    def test_business_phones_and_flag(self):
        dc = Contact.objects.create(first_name='D', last_name='C', email='dc@b.test')
        b = Business.objects.create(business_name='Acme', default_contact=dc,
                                    phones=[{'number': '555-0100', 'label': 'main'},
                                            {'number': '555-0200', 'label': 'A/P'}])
        b.refresh_from_db()
        self.assertEqual(b.phone(), '555-0100')
        self.assertEqual(b.phones_digits, '5550100 5550200')
        self.assertTrue(b.is_active)

    def test_business_phones_excluded_digits_from_history(self):
        from apps.core.models import CrmHistory
        dc = Contact.objects.create(first_name='D', last_name='C', email='dc2@b.test')
        b = Business.objects.create(business_name='Acme2', default_contact=dc)
        b.phones = [{'number': '555-0100', 'label': ''}]
        b.save()
        entry = CrmHistory.objects.filter(object_type='business', object_id=b.pk,
                                          entry_type='audit').order_by('-pk').first()
        self.assertIsNotNone(entry)
        self.assertIn('phones', entry.changes)
        self.assertNotIn('phones_digits', entry.changes)
