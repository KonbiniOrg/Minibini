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

    def test_base_reference(self):
        self.assertEqual(P.base_reference('07754'), '07754')
        self.assertEqual(P.base_reference('03024b'), '03024')
        self.assertEqual(P.base_reference('03077-SOLID'), '03077')
        self.assertEqual(P.base_reference('03108-rev2'), '03108')

    def test_hours_to_duration(self):
        self.assertEqual(P.hours_to_duration('4'), '04:00:00')
        self.assertEqual(P.hours_to_duration('1.5'), '01:30:00')
        self.assertIsNone(P.hours_to_duration(''))

    def test_parse_kanban_name(self):
        self.assertEqual(P.parse_kanban_name('Acme (Jo Roe)'), ('Acme', 'Jo Roe'))
        self.assertEqual(P.parse_kanban_name('Acme'), ('Acme', None))


class ClassifyTest(unittest.TestCase):
    def test_comment_is_skipped(self):
        self.assertEqual(P.classify_line_item('Comment', 'anything'), 'skip')

    def test_item_type_drives_classification(self):
        self.assertEqual(P.classify_line_item('Hours', 'cut parts'), 'task')
        self.assertEqual(P.classify_line_item('Days', 'design'), 'task')
        self.assertEqual(P.classify_line_item('Services', 'consult'), 'task')
        self.assertEqual(P.classify_line_item('Products', 'plywood'), 'material')
        self.assertEqual(P.classify_line_item('Expenses', 'shipping'), 'material')
        self.assertEqual(P.classify_line_item('Discount', 'x'), 'lineitem')
        self.assertEqual(P.classify_line_item('Credit', 'x'), 'lineitem')

    def test_no_unit_uses_keyword_heuristic(self):
        self.assertEqual(
            P.classify_line_item('-no unit-', '3 sheets of 3/4" plywood'), 'material')
        self.assertEqual(
            P.classify_line_item('-no unit-', 'CNC cutting of wall parts'), 'task')

    def test_algorithm_inference(self):
        self.assertEqual(P.infer_algorithm('Hours', 'hours'), 'elapsed_time')
        self.assertEqual(P.infer_algorithm('Days', 'days'), 'elapsed_time')
        self.assertEqual(P.infer_algorithm('Services', ''), 'flat_fee')
        self.assertEqual(P.infer_algorithm('-no unit-', 'each'), 'entered_qty')
        self.assertEqual(P.infer_algorithm('-no unit-', ''), 'flat_fee')
