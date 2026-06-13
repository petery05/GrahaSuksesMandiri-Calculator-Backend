"""Pure pricing engine — the single source of truth for quote math.

Ported verbatim from the prototype's gsm-data.jsx (computeLine / computeQuote)
so results are bit-identical. All arithmetic is done in float (IEEE-754 double,
same as JavaScript) on a plain-dict PricingContext; no DB access happens here,
which keeps the math unit-testable in isolation. services.py builds the context
from the ORM and persists the snapshot.
"""
import math
from dataclasses import dataclass


def js_round(x):
    """Match JavaScript's Math.round (half away from zero for positives).

    Python's built-in round() uses banker's rounding, which would diverge on .5
    cases — all our money is positive, so floor(x + 0.5) reproduces Math.round.
    """
    return math.floor(x + 0.5)


def fmt_idr(n):
    return 'Rp ' + f'{js_round(n):,}'.replace(',', '.')


def fmt_kg(n):
    return f'{n:.1f}'.replace('.', ',') + ' kg'


@dataclass
class PricingContext:
    partner: dict      # {code, basis, rate_per_kg}
    products: dict     # code -> {name_id, name_en, kg_per_m, glass_factor, kit:[codes], unit_price}
    kit: dict          # code -> {name_id, name_en, kg_per_m, unit_price}
    glass: dict        # code -> {name_id, name_en, rate}
    finishes: dict     # code -> {name_id, name_en, factor}
    service: dict      # {assembly_per_opening, logistics_flat, install_per_day, units_per_install_day}


def _loc(item, lang):
    """Localized display name for a catalog item."""
    return item['name_id'] if lang == 'id' else item['name_en']


def _kg_parts(prod, ctx, finish, perimeter, lang):
    """Profile + auto-kit parts for a weight-priced (per-kg) partner."""
    rate = ctx.partner['rate_per_kg']
    prof_kg = perimeter * prod['kg_per_m']
    parts = [{
        'key': 'profiles',
        'name': 'Profil aluminium — rangka & daun' if lang == 'id' else 'Aluminum profiles — frame & sash',
        'basis': fmt_kg(prof_kg) + ' × ' + fmt_idr(rate) + '/kg',
        'price': prof_kg * rate * finish['factor'],
        'auto': False,
    }]
    for code in prod['kit']:
        lib = ctx.kit[code]
        kg = lib['kg_per_m'] * perimeter
        parts.append({
            'key': code, 'name': _loc(lib, lang),
            'basis': fmt_kg(kg) + ' × ' + fmt_idr(rate) + '/kg',
            'price': kg * rate, 'auto': True,
        })
    return parts


def _unit_parts(prod, ctx, finish, lang):
    """Profile + auto-kit parts for a per-unit partner."""
    unit_price = prod['unit_price']
    parts = [{
        'key': 'profiles',
        'name': 'Rangka & daun (set pabrik)' if lang == 'id' else 'Frame & sash (factory set)',
        'basis': '1 unit × ' + fmt_idr(unit_price),
        'price': unit_price * finish['factor'],
        'auto': False,
    }]
    for code in prod['kit']:
        lib = ctx.kit[code]
        parts.append({
            'key': code, 'name': _loc(lib, lang),
            'basis': '1 set × ' + fmt_idr(lib['unit_price']),
            'price': lib['unit_price'], 'auto': True,
        })
    return parts


def compute_line(line, ctx, lang):
    """Price a single configured opening. Mirrors prototype computeLine()."""
    prod = ctx.products[line['product']]
    glass = ctx.glass[line['glass']]
    finish = ctx.finishes[line['finish']]
    w = float(line['width'])
    h = float(line['height'])
    qty = int(line['qty'])
    perimeter = 2 * (w + h) / 1000   # m
    area = (w * h) / 1e6             # m²

    if ctx.partner['basis'] == 'kg':
        parts = _kg_parts(prod, ctx, finish, perimeter, lang)
    else:
        parts = _unit_parts(prod, ctx, finish, lang)

    glass_area = area * prod['glass_factor']
    parts.append({
        'key': 'glass',
        'name': _loc(glass, lang),
        'basis': f'{glass_area:.2f}'.replace('.', ',') + ' m² × ' + fmt_idr(glass['rate']) + '/m²',
        'price': glass_area * glass['rate'],
        'auto': False,
    })

    per_unit = sum(p['price'] for p in parts)
    small_parts = sum(p['price'] for p in parts if p['auto'])
    return {
        'product': line['product'],
        'product_name_id': prod['name_id'],
        'product_name_en': prod['name_en'],
        'glass': line['glass'],
        'finish': line['finish'],
        'width': int(w), 'height': int(h), 'qty': qty,
        'parts': parts,
        'per_unit': per_unit,
        'total': per_unit * qty,
        'small_parts_per_unit': small_parts,
    }


def compute_quote(quote, ctx, lang):
    """Aggregate a full quote. Mirrors prototype computeQuote()."""
    lines = [compute_line(ln, ctx, lang) for ln in quote['lines']]
    has_lines = len(lines) > 0
    total_qty = sum(int(ln['qty']) for ln in quote['lines'])
    materials = sum((ln['per_unit'] - ln['small_parts_per_unit']) * ln['qty'] for ln in lines)
    small_parts = sum(ln['small_parts_per_unit'] * ln['qty'] for ln in lines)
    sr = ctx.service
    assembly = total_qty * sr['assembly_per_opening']
    logistics = sr['logistics_flat'] if has_lines else 0.0
    install_days = max(1, math.ceil(total_qty / sr['units_per_install_day'])) if total_qty else 1
    installation = install_days * sr['install_per_day'] if has_lines else 0.0
    cost_subtotal = materials + small_parts + assembly + logistics + installation
    margin_pct = float(quote.get('margin_pct', 0))
    margin_amount = cost_subtotal * (margin_pct / 100)
    return {
        'lines': lines,
        'total_qty': total_qty,
        'materials': materials,
        'small_parts': small_parts,
        'assembly': assembly,
        'logistics': logistics,
        'install_days': install_days,
        'installation': installation,
        'cost_subtotal': cost_subtotal,
        'margin_pct': margin_pct,
        'margin_amount': margin_amount,
        'grand_total': cost_subtotal + margin_amount,
    }
