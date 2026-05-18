# tests/test_neals_parsing.py
import unittest
from datetime import datetime
from decimal import Decimal
from nealsdata.converter import parsing as P


class ParsingTest(unittest.TestCase):
    def test_parse_decimal(self):
        self.assertEqual(P.parse_decimal('$1,234.50'), Decimal('1234.50'))
        self.assertEqual(P.parse_decimal(None), Decimal('0'))
        self.assertEqual(P.parse_decimal(12), Decimal('12'))

    def test_format_date(self):
        self.assertEqual(P.format_date(datetime(2026, 2, 3, 4, 56)), '2026-02-03')
        self.assertEqual(P.format_date('2026-02-03 04:56'), '2026-02-03')
        self.assertIsNone(P.format_date(None))

    def test_split_name(self):
        self.assertEqual(P.split_name('Jo Roe'), ('Jo', 'Roe'))
        self.assertEqual(P.split_name(''), ('(unknown)', '(unknown)'))
        self.assertEqual(P.split_name('Cher'), ('Cher', '(unknown)'))

    def test_revision_base_and_suffix(self):
        self.assertEqual(P.revision_parts('03024'), ('03024', 0))
        self.assertEqual(P.revision_parts('03024b'), ('03024', 1))
        self.assertEqual(P.revision_parts('03024c'), ('03024', 2))

    def test_hours_to_duration(self):
        self.assertEqual(P.hours_to_duration('4'), '04:00:00')
        self.assertEqual(P.hours_to_duration('1.5'), '01:30:00')
        self.assertIsNone(P.hours_to_duration(''))

    def test_parse_kanban_name(self):
        self.assertEqual(P.parse_kanban_name('Acme (Jo Roe)'), ('Acme', 'Jo Roe'))
        self.assertEqual(P.parse_kanban_name('Acme'), ('Acme', None))
