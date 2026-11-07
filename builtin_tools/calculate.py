"""Exact calculator: arithmetic, unit conversion and date maths, worked out locally.

Small language models are bad at arithmetic, so the Assistant hands sums to this tool.
Arithmetic goes through a whitelist AST evaluator (never eval/exec) using exact
fractions where possible, so 0.1 + 0.2 really is 0.3.
"""
import ast
import calendar
import datetime
import math
import re
from fractions import Fraction

from .svgkit import text_result

MAX_LEN = 500
LIMIT_BITS = 10000          # about 3,000 decimal digits
MAX_DIGITS = 3000

TOOLS = [{
    'name': 'calculate',
    'description': ('Exact maths. Use for ANY arithmetic, percentage, unit conversion or date question instead of '
                    'working it out yourself. Pass one expression, e.g. "(12.5*4)^2", "sqrt(2)", "15% of 80", '
                    '"200 + 10%", "5 km in miles", "72 F to C", "1 GiB to MiB", "days between 2026-01-01 and '
                    '2026-12-25", "2026-11-07 + 90 days", "weekday of 2026-12-25", "today + 30 days". '
                    'log(x) is base 10, ln(x) natural; trig in radians, sind/cosd/tand in degrees.'),
    'inputSchema': {
        'type': 'object',
        'properties': {'expression': {'type': 'string', 'minLength': 1, 'maxLength': MAX_LEN,
                                      'description': 'Maths expression, unit conversion ("3.5 lb to kg") or date '
                                                     'question (ISO dates YYYY-MM-DD).'}},
        'required': ['expression'],
        'additionalProperties': False,
    },
    'returnsImage': False,
}]


class CalcError(Exception):
    pass


def _error(message):
    return {'isError': True, 'content': [{'type': 'text', 'text': str(message)}]}


def _today():
    return datetime.date.today()


# ---------------------------------------------------------------- number formatting

def _group(int_text):
    sign = '-' if int_text.startswith('-') else ''
    digits = int_text.lstrip('-')
    return sign + f'{int(digits):,}'


def _plain(value):
    """Unseparated text for a number, floats rounded to 12 significant digits."""
    if isinstance(value, Fraction):
        if value.denominator == 1:
            return str(value.numerator)
        value = _to_float(value)
    if isinstance(value, int):
        return str(value)
    if value == 0:
        return '0'
    text = f'{value:.12g}'
    if 'e' in text:
        mantissa, exponent = text.split('e')
        exponent = int(exponent)
        if -7 <= exponent < 15:
            from decimal import Decimal
            text = format(Decimal(text), 'f')
            if '.' in text:
                text = text.rstrip('0').rstrip('.')
        else:
            return f'{mantissa}e{exponent}'
    if text in ('-0',):
        text = '0'
    return text


def _display(value):
    """(display text with thousands separators, raw text or None)."""
    raw = _plain(value)
    if 'e' in raw:
        return raw, None
    int_part, _, frac = raw.partition('.')
    if len(int_part.lstrip('-')) <= 4:
        return raw, None
    if len(int_part.lstrip('-')) > MAX_DIGITS:
        raise CalcError('The result is too large to show (over 3,000 digits).')
    shown = _group(int_part) + ('.' + frac if frac else '')
    return shown, raw


def _exact_note(value):
    """' (exactly 1/3)' for simple fractions that don't terminate in decimal."""
    if isinstance(value, Fraction) and value.denominator != 1 and value.denominator <= 10000:
        d = value.denominator
        for p in (2, 5):
            while d % p == 0:
                d //= p
        if d != 1:
            return f' (exactly {value.numerator}/{value.denominator})'
    return ''


# ---------------------------------------------------------------- arithmetic evaluator

def _to_float(value):
    try:
        result = float(value)
    except OverflowError:
        raise CalcError('The number is too large to work with here.')
    if not math.isfinite(result):
        raise CalcError('The result is too large (or undefined) to show.')
    return result


def _exact(value):
    return isinstance(value, (int, Fraction)) and not isinstance(value, bool)


def _norm(value):
    if isinstance(value, bool):
        raise CalcError('Only numbers are allowed.')
    if isinstance(value, Fraction):
        if value.denominator == 1:
            value = value.numerator
        elif value.numerator.bit_length() > LIMIT_BITS or value.denominator.bit_length() > LIMIT_BITS:
            value = _to_float(value)
    if isinstance(value, int):
        if value.bit_length() > LIMIT_BITS:
            raise CalcError('The result is too large (over 3,000 digits). Try a smaller power or factorial.')
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CalcError('The result is too large (or undefined) to show.')
        return value
    if isinstance(value, Fraction):
        return value
    raise CalcError('Only real numbers are supported.')


def _as_int(value, what):
    if isinstance(value, Fraction) and value.denominator == 1:
        value = value.numerator
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        value = int(value)
    if not isinstance(value, int):
        raise CalcError(f'{what} needs whole numbers.')
    return value


def _snap(value):
    """Tiny floating-point noise from trig (sin(pi) = 1.2e-16) becomes 0."""
    return 0 if isinstance(value, float) and abs(value) < 1e-12 else value


def _pow(base, exponent):
    if _exact(exponent) and Fraction(exponent).denominator == 1:
        n = int(exponent)
        if _exact(base):
            base = Fraction(base)
            if base == 0:
                if n < 0:
                    raise CalcError("Division by zero isn't defined (0 to a negative power).")
                return 1 if n == 0 else 0
            if abs(base) != 1:
                size = max(abs(base.numerator).bit_length(), base.denominator.bit_length())
                if abs(n) * (size - 1) > LIMIT_BITS:
                    raise CalcError('That power is too large to compute exactly (over 3,000 digits).')
            if abs(n) > 10 ** 6:
                return (1 if n % 2 == 0 else base) if abs(base) == 1 else 0
            return base ** n
    b, x = _to_float(base), _to_float(exponent)
    if b < 0 and not float(x).is_integer():
        raise CalcError('A negative number to a fractional power is not a real number.')
    if b == 0 and x < 0:
        raise CalcError("Division by zero isn't defined (0 to a negative power).")
    try:
        return math.pow(b, x)
    except OverflowError:
        raise CalcError('That power is too large to show.')


def _binop(op, a, b):
    if isinstance(op, ast.Add):
        return a + b
    if isinstance(op, ast.Sub):
        return a - b
    if isinstance(op, ast.Mult):
        return a * b
    if isinstance(op, (ast.Div, ast.FloorDiv, ast.Mod)) and b == 0:
        raise CalcError("Division by zero isn't defined.")
    if isinstance(op, ast.Div):
        return Fraction(a) / Fraction(b) if _exact(a) and _exact(b) else a / b
    if isinstance(op, ast.FloorDiv):
        return a // b
    if isinstance(op, ast.Mod):
        return a % b
    if isinstance(op, ast.Pow):
        return _pow(a, b)
    raise CalcError('Only + - * / // % and ^ (power) are allowed.')


def _real_fraction(value):
    return value if _exact(value) else Fraction(repr(float(value)))


def _f_sqrt(x):
    if x < 0:
        raise CalcError('sqrt of a negative number is not a real number.')
    if _exact(x):
        f = Fraction(x)
        rn, rd = math.isqrt(f.numerator), math.isqrt(f.denominator)
        if rn * rn == f.numerator and rd * rd == f.denominator:
            return Fraction(rn, rd)
        return math.sqrt(_to_float(f)) if f.numerator.bit_length() < 1000 else math.sqrt(f.numerator) / math.sqrt(f.denominator)
    return math.sqrt(x)


def _f_cbrt(x):
    if _exact(x) and Fraction(x).denominator == 1:
        n = int(x)
        guess = round(abs(_to_float(n)) ** (1 / 3)) if n.bit_length() < 1000 else None
        if guess is not None:
            for g in (guess - 1, guess, guess + 1):
                if g >= 0 and g ** 3 == abs(n):
                    return g if n >= 0 else -g
    v = _to_float(x)
    return math.copysign(abs(v) ** (1 / 3), v)


def _f_round(x, digits=0):
    digits = _as_int(digits, 'round(x, n)')
    if not -15 <= digits <= 15:
        raise CalcError('round(x, n) needs n between -15 and 15.')
    f = _real_fraction(x)
    scale = Fraction(10) ** digits
    sign = -1 if f < 0 else 1
    result = sign * math.floor(abs(f) * scale + Fraction(1, 2)) / scale
    return result


def _f_log(x, base=10):
    if x <= 0:
        raise CalcError('log is only defined for positive numbers.')
    if base <= 0 or base == 1:
        raise CalcError('The log base must be positive and not 1.')
    if base == 10:
        r = math.log10(x)
    elif base == 2:
        r = math.log2(x)
    else:
        r = math.log(x) / math.log(base)
    rounded = round(r)
    if abs(r - rounded) < 1e-9 and _exact(x) and _exact(base) and abs(rounded) < 4000:
        if Fraction(base) ** rounded == Fraction(x):
            return rounded
    return r


def _f_ln(x):
    if x <= 0:
        raise CalcError('ln is only defined for positive numbers.')
    return math.log(x)


def _f_log10(x):
    return _f_log(x, 10)


def _f_log2(x):
    return _f_log(x, 2)


def _f_exp(x):
    try:
        return math.exp(_to_float(x))
    except OverflowError:
        raise CalcError('exp of that number is too large to show.')


def _trig(fn, degrees=False):
    def run(x):
        v = _to_float(x)
        if degrees:
            if fn is math.tan and _exact(x) and Fraction(x) % 180 == 90:
                raise CalcError('tan is undefined at 90 degrees (and 270, ...).')
            v = math.radians(v)
        return _snap(fn(v))
    return run


def _inverse_trig(fn, name):
    def run(x):
        v = _to_float(x)
        if fn is not math.atan and not -1 <= v <= 1:
            raise CalcError(f'{name} needs a value between -1 and 1.')
        return _snap(fn(v))
    return run


def _f_factorial(x):
    n = _as_int(x, 'factorial')
    if not 0 <= n <= 170:
        raise CalcError('factorial needs a whole number from 0 to 170.')
    return math.factorial(n)


def _f_gcd(*args):
    return math.gcd(*[_as_int(a, 'gcd') for a in args])


def _f_lcm(*args):
    return math.lcm(*[_as_int(a, 'lcm') for a in args])


def _f_hypot(*args):
    if all(_exact(a) for a in args):
        return _f_sqrt(sum(Fraction(a) ** 2 for a in args))
    return math.hypot(*[_to_float(a) for a in args])


FUNCS = {   # name -> (function, min args, max args)
    'sqrt': (_f_sqrt, 1, 1), 'cbrt': (_f_cbrt, 1, 1), 'abs': (abs, 1, 1), 'round': (_f_round, 1, 2),
    'floor': (math.floor, 1, 1), 'ceil': (math.ceil, 1, 1),
    'log': (_f_log, 1, 2), 'log10': (_f_log10, 1, 1), 'log2': (_f_log2, 1, 1), 'ln': (_f_ln, 1, 1),
    'exp': (_f_exp, 1, 1),
    'sin': (_trig(math.sin), 1, 1), 'cos': (_trig(math.cos), 1, 1), 'tan': (_trig(math.tan), 1, 1),
    'sind': (_trig(math.sin, True), 1, 1), 'cosd': (_trig(math.cos, True), 1, 1),
    'tand': (_trig(math.tan, True), 1, 1),
    'asin': (_inverse_trig(math.asin, 'asin'), 1, 1), 'acos': (_inverse_trig(math.acos, 'acos'), 1, 1),
    'atan': (_inverse_trig(math.atan, 'atan'), 1, 1),
    'factorial': (_f_factorial, 1, 1), 'gcd': (_f_gcd, 1, 50), 'lcm': (_f_lcm, 1, 50),
    'min': (min, 1, 100), 'max': (max, 1, 100), 'hypot': (_f_hypot, 1, 50),
}
CONSTANTS = {'pi': math.pi, 'e': math.e, 'tau': math.tau}
FUNC_LIST = ', '.join(sorted(FUNCS))


def _is_pct(node):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == '_pct'


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CalcError('Only numbers are allowed (no text, quotes or complex numbers).')
        if isinstance(value, float):
            if not math.isfinite(value):
                raise CalcError('That number is too large.')
            return _norm(Fraction(repr(value)))
        return _norm(value)
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, (ast.Add, ast.Sub)) and _is_pct(node.right):
            left = _eval(node.left)
            pct = _eval(node.right.args[0])
            factor = Fraction(1) + pct / 100 if isinstance(node.op, ast.Add) else Fraction(1) - pct / 100
            return _norm(left * factor if _exact(left) else left * float(factor))
        return _norm(_binop(node.op, _eval(node.left), _eval(node.right)))
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.USub):
            return _norm(-_eval(node.operand))
        if isinstance(node.op, ast.UAdd):
            return _eval(node.operand)
        raise CalcError('Only + and - signs are allowed in front of numbers.')
    if isinstance(node, ast.Name):
        if node.id in CONSTANTS:
            return CONSTANTS[node.id]
        if node.id in FUNCS:
            raise CalcError(f'{node.id} is a function: write it with brackets, e.g. {node.id}(2).')
        raise CalcError(f'Unknown name "{node.id}". Known: pi, e, and functions {FUNC_LIST}.')
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise CalcError('Only plain maths functions are allowed, like sqrt(2).')
        name = node.func.id
        if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
            raise CalcError('Pass function arguments as plain numbers, e.g. round(2.567, 2).')
        if name == '_pct':
            pct = _eval(node.args[0])
            return _norm(Fraction(pct) / 100 if _exact(pct) else pct / 100)
        if name not in FUNCS:
            raise CalcError(f'Unknown function "{name}". Available: {FUNC_LIST}.')
        fn, low, high = FUNCS[name]
        if not low <= len(node.args) <= high:
            count = f'{low}' if low == high else f'{low} to {high}'
            raise CalcError(f'{name} takes {count} argument(s).')
        args = [_eval(a) for a in node.args]
        try:
            return _norm(fn(*args))
        except (ValueError, ZeroDivisionError):
            raise CalcError(f'{name} is not defined for that input.')
    if isinstance(node, ast.Attribute):
        raise CalcError('Attribute access (dots after names) is not allowed. Use plain maths only.')
    if isinstance(node, ast.Lambda):
        raise CalcError('Lambdas are not allowed. Use plain maths only.')
    if isinstance(node, (ast.Tuple, ast.List)):
        raise CalcError("Commas only separate function arguments. Don't use thousands separators inside "
                        'function calls (write 1000000, not 1,000,000).')
    if isinstance(node, ast.Compare):
        raise CalcError('Comparisons are not supported; this tool calculates values.')
    if isinstance(node, ast.BoolOp):
        raise CalcError('and/or are not supported; this tool calculates values.')
    raise CalcError('That is not plain maths. Use numbers, + - * / ^ %, brackets and functions like sqrt().')


PCT_RE = re.compile(r'(\d+(?:\.\d*)?|\.\d+)\s*%(?=\s*(?:$|[)+\-*/,]|of\b))')


def _prepare(text):
    s = text.lower()
    for old, new in (('×', '*'), ('÷', '/'), ('−', '-'), ('–', '-'), ('·', '*'), ('π', 'pi'),
                     ('²', '**2'), ('³', '**3'), ('^', '**')):
        s = s.replace(old, new)
    s = re.sub(r'√\s*(\d+(?:\.\d+)?|pi|e)', r'sqrt(\1)', s)
    s = s.replace('√', 'sqrt')
    s = re.sub(r'(?<=[\d)])\s*x\s*(?=[\d(.])', '*', s)
    if not re.search(r'[a-z]\s*\(', s):
        s = re.sub(r'(?<=\d),(?=\d{3}(?:\D|$))', '', s)
    s = PCT_RE.sub(r'_pct(\1)', s)
    s = re.sub(r'(?<=\))\s*of\b', ' *', s)
    return s.strip()


def _arith(text):
    if '_' in text:
        raise CalcError('Only numbers, operators (+ - * / ^ %), brackets and maths functions are allowed.')
    prepared = _prepare(text)
    if not prepared:
        raise CalcError('The expression is empty.')
    try:
        tree = ast.parse(prepared, mode='eval')
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        raise CalcError('I could not read that expression. Use numbers, + - * / ^ %, brackets and functions '
                        'like sqrt(2), e.g. "(3 + 4) * 2".')
    try:
        return _eval(tree)
    except RecursionError:
        raise CalcError('The expression is nested too deeply.')
    except OverflowError:
        raise CalcError('The result is too large to show.')


def _number_result(working, value):
    shown, raw = _display(value)
    lines = [f'Result: {shown}{_exact_note(value)}', f'Working: {working} = {shown}']
    if raw:
        lines.append(f'Raw value: {raw}')
    return '\n'.join(lines)


# ---------------------------------------------------------------- units

UNITS = {}      # alias -> (category, symbol, factor to base unit as Fraction or None for temperature)
CATEGORY_UNITS = {}


def _unit(category, symbol, factor, *aliases):
    factor = Fraction(factor) if factor is not None else None
    CATEGORY_UNITS.setdefault(category, []).append(symbol)
    names = {symbol.lower(), *aliases}
    for alias in list(names):
        if alias[-1:].isalpha() and len(alias) > 3 and not alias.endswith('s') and '/' not in alias:
            names.add(alias + 's')
    for alias in names:
        UNITS[alias] = (category, symbol, factor)


# length (metre)
_unit('length', 'nm', '1e-9', 'nanometer', 'nanometre')
_unit('length', 'µm', '1e-6', 'um', 'micrometer', 'micrometre', 'micron')
_unit('length', 'mm', '0.001', 'millimeter', 'millimetre')
_unit('length', 'cm', '0.01', 'centimeter', 'centimetre')
_unit('length', 'm', '1', 'meter', 'metre')
_unit('length', 'km', '1000', 'kilometer', 'kilometre')
_unit('length', 'in', '0.0254', 'inch', 'inches', '"')
_unit('length', 'ft', '0.3048', 'foot', 'feet', "'")
_unit('length', 'yd', '0.9144', 'yard')
_unit('length', 'mi', '1609.344', 'mile')
_unit('length', 'nmi', '1852', 'nautical mile')
# mass (kilogram)
_unit('mass', 'mg', '1e-6', 'milligram')
_unit('mass', 'g', '0.001', 'gram', 'gramme')
_unit('mass', 'kg', '1', 'kilogram', 'kilo')
_unit('mass', 't', '1000', 'tonne', 'metric ton')
_unit('mass', 'oz', '0.028349523125', 'ounce')
_unit('mass', 'lb', '0.45359237', 'lbs', 'pound')
_unit('mass', 'st', '6.35029318', 'stone')
_unit('mass', 'short ton', '907.18474', 'ton', 'tons', 'us ton')
# volume (litre)
_unit('volume', 'ml', '0.001', 'milliliter', 'millilitre', 'cm3', 'cm³', 'cc')
_unit('volume', 'cl', '0.01', 'centiliter', 'centilitre')
_unit('volume', 'dl', '0.1', 'deciliter', 'decilitre')
_unit('volume', 'L', '1', 'l', 'liter', 'litre')
_unit('volume', 'm³', '1000', 'm3', 'cubic meter', 'cubic metre')
_unit('volume', 'tsp', '0.00492892159375', 'teaspoon')
_unit('volume', 'tbsp', '0.01478676478125', 'tablespoon')
_unit('volume', 'fl oz', '0.0295735295625', 'floz', 'fluid ounce')
_unit('volume', 'cup', '0.2365882365', 'cups')
_unit('volume', 'pt', '0.473176473', 'pint')
_unit('volume', 'qt', '0.946352946', 'quart')
_unit('volume', 'gal', '3.785411784', 'gallon', 'us gallon')
_unit('volume', 'imp gal', '4.54609', 'imperial gallon', 'uk gallon')
_unit('volume', 'in³', '0.016387064', 'in3', 'cubic inch', 'cubic inches')
_unit('volume', 'ft³', '28.316846592', 'ft3', 'cubic foot', 'cubic feet')
# temperature (special: offsets)
_unit('temperature', '°C', None, 'c', 'celsius', 'degc', 'deg c', 'degrees c', 'degrees celsius', 'centigrade')
_unit('temperature', '°F', None, 'f', 'fahrenheit', 'degf', 'deg f', 'degrees f', 'degrees fahrenheit')
_unit('temperature', 'K', None, 'k', 'kelvin')
# speed (metre per second)
_unit('speed', 'm/s', '1', 'mps', 'meters per second', 'metres per second')
_unit('speed', 'km/h', Fraction(1000, 3600), 'kmh', 'kph', 'kmph', 'km per hour', 'kilometers per hour',
      'kilometres per hour')
_unit('speed', 'mph', Fraction(1609344, 3600000), 'mi/h', 'miles per hour')
_unit('speed', 'kn', Fraction(1852, 3600), 'knot', 'kt', 'kts')
_unit('speed', 'ft/s', '0.3048', 'fps', 'feet per second')
# time (second)
_unit('time', 'ms', '0.001', 'millisecond')
_unit('time', 's', '1', 'sec', 'secs', 'second')
_unit('time', 'min', '60', 'mins', 'minute')
_unit('time', 'h', '3600', 'hr', 'hrs', 'hour')
_unit('time', 'day', '86400', 'days', 'd')
_unit('time', 'week', '604800', 'weeks', 'wk', 'wks')
_unit('time', 'month', Fraction(2629746), 'months')          # average Gregorian month
_unit('time', 'year', Fraction(31556952), 'years', 'yr', 'yrs')  # average Gregorian year
# data (byte). Decimal KB/MB/GB = 1000^n, binary KiB/MiB/GiB = 1024^n.
_unit('data', 'bit', Fraction(1, 8), 'bits')
_unit('data', 'B', '1', 'b', 'byte')
for _i, (_d, _bn) in enumerate((('KB', 'KiB'), ('MB', 'MiB'), ('GB', 'GiB'), ('TB', 'TiB'), ('PB', 'PiB')), 1):
    _prefix = _d[0].lower()
    _unit('data', _d, 1000 ** _i, _prefix + 'byte', {'k': 'kilo', 'm': 'mega', 'g': 'giga', 't': 'tera', 'p': 'peta'}[_prefix] + 'byte')
    _unit('data', _bn, 1024 ** _i, {'k': 'kibi', 'm': 'mebi', 'g': 'gibi', 't': 'tebi', 'p': 'pebi'}[_prefix] + 'byte')
    _unit('data', _d[0] + 'bit', Fraction(1000 ** _i, 8), _prefix + 'bits', _prefix + 'bps')
# area (square metre)
_unit('area', 'mm²', '1e-6', 'mm2', 'sq mm')
_unit('area', 'cm²', '1e-4', 'cm2', 'sq cm')
_unit('area', 'm²', '1', 'm2', 'sqm', 'sq m', 'square meter', 'square metre')
_unit('area', 'km²', '1e6', 'km2', 'sq km', 'square kilometer', 'square kilometre')
_unit('area', 'in²', '0.00064516', 'in2', 'sq in', 'square inch', 'square inches')
_unit('area', 'ft²', '0.09290304', 'ft2', 'sq ft', 'sqft', 'square foot', 'square feet')
_unit('area', 'yd²', '0.83612736', 'yd2', 'sq yd', 'square yard')
_unit('area', 'mi²', '2589988.110336', 'mi2', 'sq mi', 'square mile')
_unit('area', 'acre', '4046.8564224', 'acres', 'ac')
_unit('area', 'ha', '10000', 'hectare')
# energy (joule)
_unit('energy', 'J', '1', 'j', 'joule')
_unit('energy', 'kJ', '1000', 'kj', 'kilojoule')
_unit('energy', 'MJ', '1000000', 'mj', 'megajoule')
_unit('energy', 'cal', '4.184', 'calorie')
_unit('energy', 'kcal', '4184', 'kilocalorie', 'food calorie')
_unit('energy', 'Wh', '3600', 'wh', 'watt hour')
_unit('energy', 'kWh', '3600000', 'kwh', 'kilowatt hour')
_unit('energy', 'BTU', '1055.05585262', 'btu')

_ALIASES_BY_LENGTH = sorted(UNITS, key=len, reverse=True)
SEPARATOR_RE = re.compile(r'(?<=\s)(?:into|in|to|as)(?=\s)|(?:->|=>|→)')


def _categories_text():
    return '; '.join(f'{cat}: {", ".join(units)}' for cat, units in CATEGORY_UNITS.items())


def _lookup_unit(text):
    key = re.sub(r'\s+', ' ', text.strip().lower()).rstrip('.')
    if key.startswith('degrees ') and key not in UNITS:
        key = key[len('degrees '):]
    return UNITS.get(key)


def _to_kelvin(value, symbol):
    if symbol == '°C':
        return value + Fraction('273.15')
    if symbol == '°F':
        return (value - 32) * Fraction(5, 9) + Fraction('273.15')
    return value


def _from_kelvin(value, symbol):
    if symbol == '°C':
        return value - Fraction('273.15')
    if symbol == '°F':
        return (value - Fraction('273.15')) * Fraction(9, 5) + 32
    return value


TEMP_WORKING = {
    ('°C', '°F'): '{x} × 9/5 + 32', ('°F', '°C'): '({x} − 32) × 5/9',
    ('°C', 'K'): '{x} + 273.15', ('K', '°C'): '{x} − 273.15',
    ('°F', 'K'): '({x} − 32) × 5/9 + 273.15', ('K', '°F'): '({x} − 273.15) × 9/5 + 32',
}


def _try_units(text):
    """Return result text for a unit conversion, None if this isn't one."""
    matches = list(SEPARATOR_RE.finditer(text))
    if not matches:
        return None
    sep = matches[-1]
    left, right = text[:sep.start()].strip(), text[sep.end():].strip()
    target = _lookup_unit(right)
    source, amount_text = None, None
    lowered = left.lower()
    for alias in _ALIASES_BY_LENGTH:
        if lowered.endswith(alias):
            rest = left[:len(left) - len(alias)]
            if alias[0].isalpha() and rest and rest[-1].isalpha():
                continue
            source, amount_text = UNITS[alias], rest.strip()
            break
    if source is None and target is None:
        return None
    if target is None:
        raise CalcError(f'Unknown unit "{right}". Supported units — {_categories_text()}.')
    if source is None:
        word = left.split()[-1] if left.split() else left
        raise CalcError(f'Unknown unit "{word}". Supported {target[0]} units: {", ".join(CATEGORY_UNITS[target[0]])}.')
    if source[0] != target[0]:
        raise CalcError(f"Can't convert {source[1]} ({source[0]}) to {target[1]} ({target[0]}). "
                        f'{source[0].capitalize()} units: {", ".join(CATEGORY_UNITS[source[0]])}.')
    amount = _arith(amount_text) if amount_text else 1
    amount = Fraction(amount) if _exact(amount) else _real_fraction(amount)
    category, s_sym, t_sym = source[0], source[1], target[1]
    x = _plain(amount)
    if category == 'temperature':
        kelvin = _to_kelvin(amount, s_sym)
        if kelvin < 0:
            raise CalcError(f'{x} {s_sym} is below absolute zero, so it is not a real temperature.')
        result = _norm(_from_kelvin(kelvin, t_sym))
        shown, _ = _display(result)
        formula = TEMP_WORKING.get((s_sym, t_sym), '{x}').format(x=x)
        return f'Result: {shown} {t_sym}\nWorking: {x} {s_sym} → {formula} = {shown} {t_sym}'
    factor = source[2] / target[2]
    result = _norm(amount * factor)
    shown, raw = _display(result)
    text_out = (f'Result: {shown} {t_sym}\n'
                f'Working: {x} {s_sym} × {_display(_norm(factor))[0]} = {shown} {t_sym} '
                f'(1 {s_sym} = {_display(_norm(factor))[0]} {t_sym})')
    if raw:
        text_out += f'\nRaw value: {raw}'
    return text_out


# ---------------------------------------------------------------- dates

DTERM = r'(?:\d{4}-\d{1,2}-\d{1,2}|today|tomorrow|yesterday|now)'
DATE_HINT = ('Dates must be ISO format YYYY-MM-DD. Try "days between 2026-01-01 and 2026-12-25", '
             '"2026-11-07 + 90 days", "weekday of 2026-12-25" or "today + 2 weeks".')
STEP_RE = re.compile(r'([+-])\s*(\d{1,7})\s*([a-z]+)')
STEP_UNITS = {'d': 'days', 'day': 'days', 'days': 'days', 'w': 'weeks', 'wk': 'weeks', 'wks': 'weeks',
              'week': 'weeks', 'weeks': 'weeks', 'mo': 'months', 'mon': 'months', 'month': 'months',
              'months': 'months', 'y': 'years', 'yr': 'years', 'yrs': 'years', 'year': 'years', 'years': 'years'}


def _date(token):
    token = token.strip()
    if token in ('today', 'now'):
        return _today()
    if token == 'tomorrow':
        return _today() + datetime.timedelta(days=1)
    if token == 'yesterday':
        return _today() - datetime.timedelta(days=1)
    year, month, day = (int(p) for p in token.split('-'))
    try:
        return datetime.date(year, month, day)
    except ValueError:
        raise CalcError(f'{token} is not a real calendar date. {DATE_HINT}')


def _add_months(d, months):
    index = d.month - 1 + months
    year, month = d.year + index // 12, index % 12 + 1
    if not 1 <= year <= 9999:
        raise CalcError('That date is outside years 1 to 9999.')
    return datetime.date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _fmt_date(d):
    return f'{d.isoformat()} ({d.strftime("%A")})'


def _span(days):
    weeks, rest = divmod(abs(days), 7)
    if weeks == 0:
        return ''
    return f' ({weeks} week{"s" * (weeks != 1)}' + (f' {rest} day{"s" * (rest != 1)}' if rest else '') + ')'


def _try_dates(text):
    s = re.sub(r'\s+', ' ', text.strip().lower())
    s = re.sub(r'^(?:what is|what\'s|whats|calculate) ', '', s)
    m = re.fullmatch(rf'(?:how many )?(days|weeks) (?:are there )?(?:between|from) ({DTERM}) (?:and|to|until|till) ({DTERM})', s)
    if m:
        a, b = _date(m.group(2)), _date(m.group(3))
        days = (b - a).days
        note = ' (the second date is earlier)' if days < 0 else ''
        if m.group(1) == 'weeks':
            weeks = _display(_norm(Fraction(days, 7)))[0]
            return (f'Result: {weeks} weeks ({days:,} days){note}\n'
                    f'Working: {b.isoformat()} − {a.isoformat()} = {days:,} days ÷ 7 = {weeks} weeks')
        return (f'Result: {days:,} days{_span(days)}{note}\n'
                f'Working: days between {a.isoformat()} and {b.isoformat()} = {days:,}')
    m = re.fullmatch(rf'(?:weekday|day of (?:the )?week|what day(?: of the week)?(?: is| was| will be)?|day)'
                     rf'(?: of| for| on| is)? ({DTERM})\??', s)
    if m:
        d = _date(m.group(1))
        return f'Result: {d.strftime("%A")}\nWorking: {d.isoformat()} is a {d.strftime("%A")}'
    m = re.fullmatch(rf'({DTERM}) ?- ?({DTERM})', s)
    if m:
        a, b = _date(m.group(1)), _date(m.group(2))
        days = (a - b).days
        return f'Result: {days:,} days{_span(days)}\nWorking: {a.isoformat()} − {b.isoformat()} = {days:,} days'
    m = re.fullmatch(rf'({DTERM})((?: ?[+-] ?\d+ ?[a-z]+)*)', s)
    if m:
        d = start = _date(m.group(1))
        steps = []
        for sign, number, unit in STEP_RE.findall(m.group(2)):
            kind = STEP_UNITS.get(unit)
            if kind is None:
                raise CalcError(f'Unknown date step "{unit}". Use days, weeks, months or years. {DATE_HINT}')
            n = int(number) * (1 if sign == '+' else -1)
            try:
                if kind == 'days':
                    d = d + datetime.timedelta(days=n)
                elif kind == 'weeks':
                    d = d + datetime.timedelta(weeks=n)
                elif kind == 'months':
                    d = _add_months(d, n)
                else:
                    d = _add_months(d, 12 * n)
            except OverflowError:
                raise CalcError('That date is outside years 1 to 9999.')
            steps.append(f'{sign} {number} {kind if int(number) != 1 else kind[:-1]}')
        if not steps:
            return f'Result: {_fmt_date(d)}\nWorking: {m.group(1)} = {_fmt_date(d)}'
        note = ''
        if any('month' in step or 'year' in step for step in steps):
            note = ' (month maths keeps the day of month, clamped to the month\'s last day)'
        return (f'Result: {_fmt_date(d)}\n'
                f'Working: {start.isoformat()} {" ".join(steps)} = {d.isoformat()}{note}')
    if re.search(r'\b\d{4}-\d{1,2}-\d{1,2}\b', s) or re.search(r'\b\d{1,2}/\d{1,2}/\d{4}\b', s) \
            or re.search(r'\b(?:today|tomorrow|yesterday|weekday)\b', s):
        raise CalcError(f'I could not read that date question. {DATE_HINT}')
    return None


# ---------------------------------------------------------------- entry point

def calculate(expression):
    text = expression.strip()
    text = re.sub(r'^(?:what is|what\'s|whats|calculate|compute|convert)\s+', '', text, flags=re.I)
    text = text.rstrip('?= ').strip()
    if not text:
        raise CalcError('The expression is empty.')
    for handler in (_try_dates, _try_units):
        result = handler(text)
        if result is not None:
            return result
    value = _arith(text)
    return _number_result(re.sub(r'\s+', ' ', text), value)


def call(tool, arguments):
    if tool != 'calculate':
        return _error(f'Unknown tool "{tool}".')
    if not isinstance(arguments, dict):
        return _error('Pass an object like {"expression": "2 + 2"}.')
    extra = set(arguments) - {'expression'}
    if extra:
        return _error(f'Unexpected argument(s): {", ".join(sorted(map(str, extra)))}. Only "expression" is allowed.')
    expression = arguments.get('expression')
    if not isinstance(expression, str) or not expression.strip():
        return _error('Pass the maths as text in "expression", e.g. "15% of 80".')
    if len(expression) > MAX_LEN:
        return _error(f'The expression is too long (max {MAX_LEN} characters).')
    try:
        return text_result(calculate(expression))
    except CalcError as error:
        return _error(error)
    except (OverflowError, MemoryError):
        return _error('The result is too large to work out.')
    except (ValueError, TypeError, ZeroDivisionError, ArithmeticError, RecursionError):
        return _error('I could not work that out. Check the expression, e.g. "(3 + 4) * 2" or "5 km in miles".')
