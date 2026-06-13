"""Seed the catalog with the prototype's reference data (idempotent).

Run with:  python manage.py seed_data
Mirrors PARTNERS / KIT_LIB / PRODUCTS / GLASS / FINISHES / SERVICE_RATES from the
design prototype (gsm-data.jsx). Safe to re-run — uses update_or_create.
"""
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from cpq.models import (
    Finish,
    GlassType,
    KitComponent,
    Partner,
    PriceList,
    Product,
    ProductKit,
    ProductUnitPrice,
    ServiceRates,
)

KIT = {
    'rollers':  ('Set roda & rel', 'Rollers & track set', '0.22', '320000'),
    'gaskets':  ('Karet gasket (EPDM)', 'Rubber gaskets (EPDM)', '0.09', '110000'),
    'brackets': ('Braket sambungan', 'Joining brackets', '0.07', '90000'),
    'screws':   ('Kit sekrup & fixing', 'Screw & fixing kit', '0.05', '55000'),
    'handle':   ('Set handle & kunci', 'Handle & lock set', '0.11', '260000'),
    'hinges':   ('Engsel heavy-duty', 'Heavy-duty hinges', '0.08', '180000'),
}

PRODUCTS = [
    # code, name_id, name_en, kg_per_m, glass_factor, {tostem, allure}, kit
    ('sliding2', 'Pintu geser — 2 panel', 'Sliding door — 2 panel', '2.6', '0.85',
     ('5200000', '5600000'), ['rollers', 'gaskets', 'brackets', 'screws', 'handle']),
    ('casement', 'Jendela casement', 'Casement window', '1.9', '0.8',
     ('2400000', '2700000'), ['hinges', 'gaskets', 'brackets', 'screws', 'handle']),
    ('fixed', 'Jendela fixed', 'Fixed window', '1.5', '0.9',
     ('1400000', '1550000'), ['gaskets', 'brackets', 'screws']),
    ('swing', 'Pintu swing', 'Swing door', '2.3', '0.7',
     ('3800000', '4150000'), ['hinges', 'gaskets', 'brackets', 'screws', 'handle']),
    ('shopfront', 'Partisi / shopfront', 'Shopfront / partition', '3.1', '0.92',
     ('6500000', '7000000'), ['gaskets', 'brackets', 'screws']),
]

GLASS = [
    ('clear6', 'Kaca bening 6mm tempered', '6mm clear tempered', '450000'),
    ('lowe6', 'Kaca Low-E 6mm', '6mm Low-E', '700000'),
    ('temp8', 'Kaca tempered 8mm', '8mm tempered', '850000'),
]

FINISHES = [
    ('pcWhite', 'Powder coat — putih', 'Powder coat — white', '1'),
    ('pcBlack', 'Powder coat — hitam', 'Powder coat — black', '1.04'),
    ('anodized', 'Anodized — silver', 'Anodized — silver', '1.08'),
    ('wood', 'Motif kayu', 'Wood-grain', '1.15'),
]

# code, name, basis, c1, c2, list version, effective date, is_current, rate_per_kg
PARTNERS = [
    ('starmas', 'Starmas', 'kg', '#B09226', '#061B9E', 'v12', date(2026, 6, 1), True, '72000'),
    ('tostem', 'TOSTEM', 'unit', '#4F4F4F', '#8a8d90', 'v8', date(2026, 5, 28), True, None),
    ('allure', 'Allure Industries', 'unit', '#000000', '#7D8082', 'v5', date(2026, 3, 12), False, None),
]


class Command(BaseCommand):
    help = 'Seed the catalog with the prototype reference data.'

    @transaction.atomic
    def handle(self, *args, **options):
        for code, (nid, nen, kgm, price) in KIT.items():
            KitComponent.objects.update_or_create(
                code=code,
                defaults={'name_id': nid, 'name_en': nen,
                          'kg_per_m': Decimal(kgm), 'unit_price': Decimal(price)},
            )

        products = {}
        for i, (code, nid, nen, kgm, gf, _unit, kit) in enumerate(PRODUCTS):
            prod, _ = Product.objects.update_or_create(
                code=code,
                defaults={'name_id': nid, 'name_en': nen, 'kg_per_m': Decimal(kgm),
                          'glass_factor': Decimal(gf), 'sort_order': i},
            )
            products[code] = prod
            for j, comp_code in enumerate(kit):
                ProductKit.objects.update_or_create(
                    product=prod, component=KitComponent.objects.get(code=comp_code),
                    defaults={'sort_order': j},
                )

        for i, (code, nid, nen, rate) in enumerate(GLASS):
            GlassType.objects.update_or_create(
                code=code,
                defaults={'name_id': nid, 'name_en': nen, 'rate': Decimal(rate), 'sort_order': i},
            )

        for i, (code, nid, nen, factor) in enumerate(FINISHES):
            Finish.objects.update_or_create(
                code=code,
                defaults={'name_id': nid, 'name_en': nen, 'factor': Decimal(factor), 'sort_order': i},
            )

        ServiceRates.objects.update_or_create(
            pk=1,
            defaults={'assembly_per_opening': Decimal('350000'), 'logistics_flat': Decimal('750000'),
                      'install_per_day': Decimal('1200000'), 'units_per_install_day': 3},
        )

        unit_index = {'tostem': 0, 'allure': 1}
        for i, (code, name, basis, c1, c2, version, eff, current, rate_kg) in enumerate(PARTNERS):
            partner, _ = Partner.objects.update_or_create(
                code=code,
                defaults={'name': name, 'basis': basis, 'color_primary': c1,
                          'color_secondary': c2, 'sort_order': i},
            )
            price_list, _ = PriceList.objects.update_or_create(
                partner=partner, version=version,
                defaults={'effective_date': eff, 'is_current': current,
                          'rate_per_kg': Decimal(rate_kg) if rate_kg else None},
            )
            if basis == 'unit':
                idx = unit_index[code]
                for (pcode, *_rest, unit_prices, _kit) in PRODUCTS:
                    ProductUnitPrice.objects.update_or_create(
                        price_list=price_list, product=products[pcode],
                        defaults={'unit_price': Decimal(unit_prices[idx])},
                    )

        # Dev-only demo sales user for testing the login flow (non-staff).
        # Guarded by DEBUG so a production seed never creates a known-password account.
        User = get_user_model()
        if settings.DEBUG and not User.objects.filter(username='sales').exists():
            User.objects.create_user('sales', password='salesdemo123')
            self.stdout.write('  created demo user "sales" (password: salesdemo123)')

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {Partner.objects.count()} partners, {Product.objects.count()} products, '
            f'{KitComponent.objects.count()} kit components, {GlassType.objects.count()} glass types, '
            f'{Finish.objects.count()} finishes.'
        ))
