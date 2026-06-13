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

    def test_format_datetime(self):
        self.assertEqual(
            P.format_datetime(datetime(2026, 2, 3, 4, 56)),
            '2026-02-03T00:00:00+00:00',
        )
        self.assertEqual(
            P.format_datetime('2026-02-03 04:56'),
            '2026-02-03T00:00:00+00:00',
        )
        self.assertIsNone(P.format_datetime(None))

    def test_split_name(self):
        self.assertEqual(P.split_name('Jo Roe'), ('Jo', 'Roe'))
        self.assertEqual(P.split_name(''), ('(unknown)', '(unknown)'))
        self.assertEqual(P.split_name('Cher'), ('Cher', '(unknown)'))

    def test_resolve_li_units_and_qty(self):
        # 'Days' → 'hours' with qty × 8 (one workday). 'Hours' stays. Anything
        # else lands on the canon default 'none' without touching qty.
        self.assertEqual(P.resolve_li_units_and_qty('Days', Decimal('1.5')),
                         ('hours', Decimal('12')))
        self.assertEqual(P.resolve_li_units_and_qty('Hours', Decimal('2')),
                         ('hours', Decimal('2')))
        self.assertEqual(P.resolve_li_units_and_qty('Each', Decimal('5')),
                         ('none', Decimal('5')))
        self.assertEqual(P.resolve_li_units_and_qty('', Decimal('3')),
                         ('none', Decimal('3')))

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

    def test_description_starting_with_cut_is_always_task(self):
        # 'Cut ...' is a labour operation, never a material — even when the
        # description contains material keywords or the Item Type says Products.
        self.assertEqual(
            P.classify_line_item('-no unit-', 'Cut acrylic racks'), 'task')
        self.assertEqual(
            P.classify_line_item('Products', 'Cut plywood panels'), 'task')
        self.assertEqual(
            P.classify_line_item('-no unit-', 'cut 6 sheets'), 'task')
        # but a 'Cut' Comment is still skipped, and a 'Cut' discount stays a line
        self.assertEqual(P.classify_line_item('Comment', 'Cut note'), 'skip')
        self.assertEqual(P.classify_line_item('Discount', 'Cut rate'), 'lineitem')

    def test_algorithm_inference(self):
        self.assertEqual(P.infer_algorithm('Hours', 'hours'), 'elapsed_time')
        self.assertEqual(P.infer_algorithm('Days', 'days'), 'elapsed_time')
        self.assertEqual(P.infer_algorithm('Services', ''), 'flat_fee')
        self.assertEqual(P.infer_algorithm('-no unit-', 'each'), 'entered_qty')
        self.assertEqual(P.infer_algorithm('-no unit-', ''), 'flat_fee')


class ChecklistTest(unittest.TestCase):
    def test_parse_checklist_basic(self):
        cell = '[ ] do a thing;\n[X] did a thing'
        items = P.parse_checklist(cell)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0],
                         {'text': 'do a thing', 'completed': False,
                          'is_subtask': False})
        self.assertEqual(items[1],
                         {'text': 'did a thing', 'completed': True,
                          'is_subtask': False})

    def test_parse_checklist_subtasks_and_blanks(self):
        cell = ('[ ] parent task;\n'
                '    [X] a finished subtask;\n'
                '\n'
                '[x] another top-level')
        items = P.parse_checklist(cell)
        self.assertEqual(len(items), 3)
        self.assertFalse(items[0]['is_subtask'])
        self.assertTrue(items[1]['is_subtask'])
        self.assertTrue(items[1]['completed'])
        self.assertFalse(items[2]['is_subtask'])
        self.assertTrue(items[2]['completed'])

    def test_parse_checklist_empty(self):
        self.assertEqual(P.parse_checklist(''), [])
        self.assertEqual(P.parse_checklist(None), [])

    def test_checklist_scheme_name(self):
        self.assertEqual(P.checklist_scheme_name('Cut 6 sheets'), 'CNC routing')
        self.assertEqual(P.checklist_scheme_name('raster laser cut'), 'Laser')
        self.assertEqual(P.checklist_scheme_name('CAD drawing'), 'CAD')
        self.assertEqual(P.checklist_scheme_name('draw the part'), 'CAD')
        self.assertEqual(P.checklist_scheme_name('model the bracket'), 'CAD')
        self.assertEqual(P.checklist_scheme_name('assemble frames'), 'Shop labor')


class SyntheticValueHelpersTest(unittest.TestCase):
    def test_thirds_factor_rotation(self):
        self.assertEqual(P.thirds_factor(0), Decimal('1.0'))
        self.assertEqual(P.thirds_factor(1), Decimal('1.10'))
        self.assertEqual(P.thirds_factor(2), Decimal('0.95'))
        self.assertEqual(P.thirds_factor(3), Decimal('1.0'))  # wraps

    def test_round_2sig(self):
        self.assertEqual(P.round_2sig(0.5), 0.5)
        self.assertEqual(P.round_2sig(0.554), 0.55)   # 2 dp below 1.0
        self.assertEqual(P.round_2sig(1.234), 1.2)    # 1 dp at/above 1.0
        self.assertEqual(P.round_2sig(3.86), 3.9)
        self.assertEqual(P.round_2sig(0), 0.0)

    def test_parse_duration(self):
        from datetime import timedelta
        self.assertEqual(P.parse_duration('01:30:00'), timedelta(hours=1, minutes=30))
        self.assertEqual(P.parse_duration('00:00:45'), timedelta(seconds=45))
        self.assertIsNone(P.parse_duration(None))
        self.assertIsNone(P.parse_duration(''))
        self.assertIsNone(P.parse_duration('garbage'))


class ThicknessExtractionTest(unittest.TestCase):
    def test_fractions_and_decimals_normalise(self):
        self.assertIn('0.75', P.extract_thicknesses('4\'x8\' x 3/4" sheet of ply'))
        self.assertIn('0.125', P.extract_thicknesses('1/8" acrylic'))
        self.assertIn('0.125', P.extract_thicknesses('x 1/8 sheet'))
        self.assertIn('0.5', P.extract_thicknesses('x .5" sheet'))
        self.assertIn('1', P.extract_thicknesses('1" thick stock'))

    def test_large_quoted_dimensions_ignored(self):
        # 48" x 96" are panel sizes, not thicknesses (> 3 inch cap).
        th = P.extract_thicknesses('48" x 96" panel')
        self.assertNotIn('48', th)
        self.assertNotIn('96', th)


class MatchPliTest(unittest.TestCase):
    PLI = [
        {'code': 'BBPLY.75', 'description': '4\'x8\' x 3/4" sheet(s) of Baltic Birch plywood'},
        {'code': 'BBPLY.25', 'description': '4\'x8\' x 1/4" sheet(s) of Baltic Birch plywood'},
        {'code': 'ACR.25', 'description': '4\'x8\' x 1/4" sheet(s) of clear acrylic'},
        {'code': 'MDF.5', 'description': '4\'x8\' x 1/2" sheet of MDF'},
    ]

    def test_matches_keyword_plus_thickness(self):
        self.assertEqual(
            P.match_pli('4\'x8\' x 3/4" sheet of Baltic Birch plywood', self.PLI),
            'BBPLY.75')
        self.assertEqual(
            P.match_pli('sheet of 1/4" clear acrylic', self.PLI), 'ACR.25')
        self.assertEqual(
            P.match_pli('sheet of 1/2" MDF from stock', self.PLI), 'MDF.5')

    def test_thickness_disambiguates_same_family(self):
        self.assertEqual(
            P.match_pli('(12) sheets 1/4" Baltic Birch plywood', self.PLI),
            'BBPLY.25')

    def test_no_thickness_or_no_family_returns_none(self):
        self.assertIsNone(P.match_pli('Baltic birch plywood from stock', self.PLI))
        self.assertIsNone(P.match_pli('3/4" sheet of unobtainium', self.PLI))
        self.assertIsNone(P.match_pli('', self.PLI))
