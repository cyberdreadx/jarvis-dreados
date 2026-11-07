import datetime
import time
import unittest
from unittest.mock import patch

from builtin_tools import calculate as c


def run(expression):
    return c.call('calculate', {'expression': expression})


def text(expression):
    result = run(expression)
    if result.get('isError'):
        raise AssertionError(f'{expression!r} failed: {result["content"][0]["text"]}')
    return result['content'][0]['text']


def result_line(expression):
    return text(expression).splitlines()[0].removeprefix('Result: ')


class SchemaTests(unittest.TestCase):
    def test_tool_definition(self):
        self.assertEqual(len(c.TOOLS), 1)
        tool = c.TOOLS[0]
        self.assertEqual(tool['name'], 'calculate')
        self.assertIs(tool['returnsImage'], False)
        self.assertLessEqual(len(tool['description']), 450)
        schema = tool['inputSchema']
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(schema['required'], ['expression'])
        self.assertEqual(schema['properties']['expression']['maxLength'], 500)

    def test_bad_arguments(self):
        for args in (None, {}, {'expression': ''}, {'expression': 5}, {'expression': 'x' * 501},
                     {'expression': '1', 'other': 2}):
            result = c.call('calculate', args)
            self.assertTrue(result['isError'], args)
        self.assertTrue(c.call('nope', {'expression': '1'})['isError'])


class ArithmeticTests(unittest.TestCase):
    def check(self, expression, expected):
        self.assertEqual(result_line(expression), expected, expression)

    def test_precedence_and_operators(self):
        self.check('2 + 3 * 4', '14')
        self.check('(2 + 3) * 4', '20')
        self.check('-3^2', '-9')
        self.check('2^3^2', '512')
        self.check('2 ** 10', '1024')
        self.check('7 / 2', '3.5')
        self.check('10 // 3', '3')
        self.check('10 % 3', '1')
        self.check('-(4 - 10)', '6')
        self.check('6 × 7 ÷ 2', '21')
        self.check('1.5e3 + 1', '1501')

    def test_exact_decimals(self):
        self.check('0.1 + 0.2', '0.3')
        self.check('1 / 3 * 3', '1')
        self.assertIn('exactly 1/3', text('1/3'))
        self.check('1 / 3', '0.333333333333 (exactly 1/3)')

    def test_large_numbers_grouped_with_raw(self):
        out = text('2^64')
        self.assertIn('Result: 18,446,744,073,709,551,616', out)
        self.assertIn('Raw value: 18446744073709551616', out)
        self.check('1,000,000 + 5', '1,000,005')

    def test_functions(self):
        self.check('sqrt(16)', '4')
        self.check('sqrt(2)', '1.41421356237')
        self.check('cbrt(-27)', '-3')
        self.check('abs(-4.5)', '4.5')
        self.check('round(2.5)', '3')
        self.check('round(2.675, 2)', '2.68')
        self.check('floor(-2.5)', '-3')
        self.check('ceil(2.1)', '3')
        self.check('log(1000)', '3')
        self.check('log(8, 2)', '3')
        self.check('log10(0.01)', '-2')
        self.check('log2(1024)', '10')
        self.check('ln(e)', '1')
        self.check('exp(0)', '1')
        self.check('sin(pi)', '0')
        self.check('cos(0)', '1')
        self.check('sind(30)', '0.5')
        self.check('cosd(60)', '0.5')
        self.check('tand(45)', '1')
        self.check('asin(1) * 2', '3.14159265359')
        self.check('factorial(10)', '3,628,800')
        self.check('gcd(12, 18)', '6')
        self.check('lcm(4, 6)', '12')
        self.check('min(3, 1, 2)', '1')
        self.check('max(3, 1, 2)', '3')
        self.check('hypot(3, 4)', '5')
        self.check('2 * pi', '6.28318530718')

    def test_percentages(self):
        self.assertEqual(text('15% of 80').splitlines()[1], 'Working: 15% of 80 = 12')
        self.check('15% of 80', '12')
        self.check('200 + 10%', '220')
        self.check('200 - 10%', '180')
        self.check('50%', '0.5')
        self.check('12.5% of 64', '8')

    def test_errors(self):
        for expression in ("__import__('os')", '().__class__', '(1).real', 'lambda: 1', '9**9**9',
                           '1/0', '5 % 0', '0 ** -1', 'sqrt(-1)', 'log(0)', 'factorial(171)', 'factorial(2.5)',
                           'tand(90)', 'exp(10000)', '"text"', 'foo(2)', 'abc', '[1, 2]', '1 < 2',
                           '(-8) ^ (1/3)', '10 ** 5000', 'asin(2)', '1e999'):
            result = run(expression)
            self.assertTrue(result.get('isError'), expression)
            self.assertTrue(result['content'][0]['text'])

    def test_power_guard_is_fast(self):
        start = time.perf_counter()
        for expression in ('9**9**9', '2**999999999', '(10**3000)*(10**3000)', 'factorial(170)**100'):
            run(expression)
        self.assertLess(time.perf_counter() - start, 0.5)


class UnitTests(unittest.TestCase):
    def value(self, expression):
        return result_line(expression)

    def test_length_mass_volume(self):
        self.assertEqual(self.value('5 km in miles'), '3.10685596119 mi')
        self.assertEqual(self.value('12 in to cm'), '30.48 cm')
        self.assertEqual(self.value('1 mile to feet'), '5280 ft')
        self.assertEqual(self.value('3.5 lb to kg'), '1.587573295 kg')
        self.assertEqual(self.value('2 cups to ml'), '473.176473 ml')
        self.assertEqual(self.value('1 gallon to L'), '3.785411784 L')

    def test_temperature_offsets(self):
        self.assertEqual(self.value('72 F to C'), '22.2222222222 °C')
        self.assertEqual(self.value('100 C to F'), '212 °F')
        self.assertEqual(self.value('-40 c to f'), '-40 °F')
        self.assertEqual(self.value('0 K to C'), '-273.15 °C')
        self.assertEqual(self.value('32 fahrenheit to kelvin'), '273.15 K')
        self.assertIn('(72 − 32) × 5/9', text('72 F to C'))
        self.assertTrue(run('-500 C to K')['isError'])

    def test_speed_time_data(self):
        self.assertEqual(self.value('100 mph in km/h'), '160.9344 km/h')
        self.assertEqual(self.value('20 m/s to km/h'), '72 km/h')
        self.assertEqual(self.value('90 minutes to hours'), '1.5 h')
        self.assertEqual(self.value('1 GB to MB'), '1000 MB')
        self.assertEqual(self.value('1 GiB to MiB'), '1024 MiB')
        self.assertEqual(self.value('8 Mbit to MB'), '1 MB')

    def test_area_energy(self):
        self.assertEqual(self.value('1 acre to m2'), '4046.8564224 m²')
        self.assertEqual(self.value('1 hectare in acres'), '2.47105381467 acre')
        self.assertEqual(self.value('100 sq ft to m2'), '9.290304 m²')
        self.assertEqual(self.value('1 kcal to kJ'), '4.184 kJ')
        self.assertEqual(self.value('1 kWh to J'), '3,600,000 J')

    def test_unit_errors(self):
        unknown = run('5 km to zorks')
        self.assertTrue(unknown['isError'])
        self.assertIn('length', unknown['content'][0]['text'])
        mismatch = run('5 km to kg')
        self.assertTrue(mismatch['isError'])
        self.assertIn('length', mismatch['content'][0]['text'])
        self.assertIn('mass', mismatch['content'][0]['text'])
        self.assertTrue(run('5 furlongs to m')['isError'])


class DateTests(unittest.TestCase):
    def test_days_between(self):
        self.assertTrue(result_line('days between 2026-01-01 and 2026-12-25').startswith('358 days'))
        self.assertTrue(result_line('2026-12-25 - 2026-01-01').startswith('358 days'))

    def test_add_days_weeks(self):
        self.assertEqual(result_line('2026-11-07 + 90 days'), '2027-02-05 (Friday)')
        self.assertEqual(result_line('2026-11-07 + 2 weeks'), '2026-11-21 (Saturday)')
        self.assertEqual(result_line('2026-11-07 - 7 days'), '2026-10-31 (Saturday)')

    def test_month_and_year_clamping(self):
        self.assertEqual(result_line('2026-01-31 + 1 month'), '2026-02-28 (Saturday)')
        self.assertEqual(result_line('2024-01-31 + 1 month'), '2024-02-29 (Thursday)')
        self.assertEqual(result_line('2026-03-31 - 1 month'), '2026-02-28 (Saturday)')
        self.assertEqual(result_line('2024-02-29 + 1 year'), '2025-02-28 (Friday)')
        self.assertEqual(result_line('2026-11-30 + 3 months'), '2027-02-28 (Sunday)')

    def test_weekday(self):
        self.assertEqual(result_line('weekday of 2026-12-25'), 'Friday')

    def test_today(self):
        with patch.object(c, '_today', return_value=datetime.date(2026, 11, 7)):
            self.assertEqual(result_line('today'), '2026-11-07 (Saturday)')
            self.assertEqual(result_line('today + 30 days'), '2026-12-07 (Monday)')

    def test_date_errors(self):
        for expression in ('2026-02-30 + 1 day', '12/25/2026 + 1 day', '2026-01-01 + 3 fortnights',
                           '9999-12-31 + 1 day'):
            result = run(expression)
            self.assertTrue(result.get('isError'), expression)
        self.assertIn('YYYY-MM-DD', run('12/25/2026 + 1 day')['content'][0]['text'])


if __name__ == '__main__':
    unittest.main()
