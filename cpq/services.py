"""Bridge between the ORM and the pure pricing engine.

build_context loads catalog + price-list data into the plain dicts pricing.py
expects; persist_quote computes a quote and freezes the result onto Quote /
QuoteLine rows (the price snapshot).
"""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from . import pricing
from .models import Finish, GlassType, KitComponent, Partner, Product, Quote, QuoteLine, ServiceRates

VALIDITY_DAYS = 14


def _money(x):
    return Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def resolve_price_list(partner):
    """The price list a quote should be priced against (current, else latest)."""
    return partner.effective_price_list


def build_context(partner, price_list, *, products=None):
    """Assemble a PricingContext from the DB.

    `products` optionally narrows the catalog to the codes actually used, but the
    catalog is tiny so loading everything is fine for the common case.
    """
    product_qs = Product.objects.prefetch_related('kit_links__component')
    if products is not None:
        product_qs = product_qs.filter(code__in=products)

    unit_prices = {}
    if price_list is not None:
        unit_prices = {
            pup.product_id: float(pup.unit_price)
            for pup in price_list.product_prices.all()
        }

    product_map = {}
    for p in product_qs:
        product_map[p.code] = {
            'name_id': p.name_id,
            'name_en': p.name_en,
            'kg_per_m': float(p.kg_per_m),
            'glass_factor': float(p.glass_factor),
            'kit': [link.component.code for link in p.kit_links.all()],
            'unit_price': unit_prices.get(p.id),
        }

    kit_map = {
        k.code: {
            'name_id': k.name_id, 'name_en': k.name_en,
            'kg_per_m': float(k.kg_per_m), 'unit_price': float(k.unit_price),
        }
        for k in KitComponent.objects.all()
    }
    glass_map = {
        g.code: {'name_id': g.name_id, 'name_en': g.name_en, 'rate': float(g.rate)}
        for g in GlassType.objects.all()
    }
    finish_map = {
        f.code: {'name_id': f.name_id, 'name_en': f.name_en, 'factor': float(f.factor)}
        for f in Finish.objects.all()
    }
    sr = ServiceRates.load()
    service = {
        'assembly_per_opening': float(sr.assembly_per_opening),
        'logistics_flat': float(sr.logistics_flat),
        'install_per_day': float(sr.install_per_day),
        'units_per_install_day': int(sr.units_per_install_day),
    }
    partner_d = {
        'code': partner.code,
        'basis': partner.basis,
        'rate_per_kg': float(price_list.rate_per_kg)
        if (price_list and price_list.rate_per_kg is not None) else None,
    }
    return pricing.PricingContext(partner_d, product_map, kit_map, glass_map, finish_map, service)


def compute_for_partner(partner, lines, margin_pct, lang='id'):
    """Compute (without persisting) using the partner's effective price list."""
    price_list = resolve_price_list(partner)
    if price_list is None:
        raise ValueError('Partner has no price list')
    ctx = build_context(partner, price_list, products={ln['product'] for ln in lines} or None)
    result = pricing.compute_quote({'lines': lines, 'margin_pct': margin_pct}, ctx, lang)
    result['partner'] = {
        'code': partner.code, 'name': partner.name, 'basis': partner.basis,
        'price_list_version': price_list.version, 'is_current': price_list.is_current,
    }
    # Service rates the totals were derived from, so the UI can show the bases
    # (e.g. "6 × Rp 350.000") without re-deriving prices client-side.
    result['rates'] = dict(ctx.service)
    return result


def _round_parts(parts):
    return [{**p, 'price': round(p['price'], 2)} for p in parts]


@transaction.atomic
def persist_quote(owner, data):
    """Compute a quote and freeze the result onto new Quote / QuoteLine rows."""
    partner = Partner.objects.get(code=data['partner'])
    price_list = resolve_price_list(partner)
    if price_list is None:
        raise ValueError('Partner has no price list')

    lines_in = data['lines']
    ctx = build_context(partner, price_list, products={ln['product'] for ln in lines_in} or None)
    computed = pricing.compute_quote(
        {'lines': lines_in, 'margin_pct': data['margin_pct']}, ctx, data.get('lang', 'id'),
    )

    today = timezone.now().date()
    quote = Quote.objects.create(
        owner=owner,
        client_name=data['client_name'],
        client_contact=data.get('client_contact', ''),
        client_site=data.get('client_site', ''),
        project_type=data.get('project_type', '0'),
        partner=partner,
        price_list=price_list,
        margin_pct=_money(data['margin_pct']),
        template_id=data.get('template_id', 'pdf'),
        materials=_money(computed['materials']),
        small_parts=_money(computed['small_parts']),
        assembly=_money(computed['assembly']),
        logistics=_money(computed['logistics']),
        installation=_money(computed['installation']),
        install_days=computed['install_days'],
        cost_subtotal=_money(computed['cost_subtotal']),
        margin_amount=_money(computed['margin_amount']),
        grand_total=_money(computed['grand_total']),
        valid_until=today + timedelta(days=VALIDITY_DAYS),
    )

    product_ids = {p.code: p.id for p in Product.objects.filter(code__in={ln['product'] for ln in lines_in})}
    glass_ids = {g.code: g.id for g in GlassType.objects.filter(code__in={ln['glass'] for ln in lines_in})}
    finish_ids = {f.code: f.id for f in Finish.objects.filter(code__in={ln['finish'] for ln in lines_in})}

    QuoteLine.objects.bulk_create([
        QuoteLine(
            quote=quote,
            product_id=product_ids[cl['product']],
            product_name_id=cl['product_name_id'],
            product_name_en=cl['product_name_en'],
            glass_id=glass_ids[cl['glass']],
            finish_id=finish_ids[cl['finish']],
            width=cl['width'], height=cl['height'], qty=cl['qty'],
            per_unit_price=_money(cl['per_unit']),
            small_parts_per_unit=_money(cl['small_parts_per_unit']),
            line_total=_money(cl['total']),
            parts=_round_parts(cl['parts']),
            sort_order=i,
        )
        for i, cl in enumerate(computed['lines'])
    ])

    quote.reference = f'Q-{1000 + quote.pk}'
    quote.save(update_fields=['reference'])
    return quote
