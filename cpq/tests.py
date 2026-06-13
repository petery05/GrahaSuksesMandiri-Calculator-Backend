from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APITestCase

from .models import Partner, Quote, ServiceRates
from .pricing import js_round
from .services import compute_for_partner

# The prototype's default quote (gsm-app.jsx DEFAULT_QUOTE) and the numbers it
# produces — these are the parity targets the backend must reproduce exactly.
DEFAULT_LINES = [
    {'product': 'sliding2', 'width': 2400, 'height': 2200, 'qty': 2, 'glass': 'clear6', 'finish': 'pcWhite'},
    {'product': 'casement', 'width': 1200, 'height': 1400, 'qty': 4, 'glass': 'clear6', 'finish': 'pcWhite'},
]
EXPECTED = {
    'materials': 12748320,
    'small_parts': 1314432,
    'assembly': 2100000,
    'logistics': 750000,
    'install_days': 2,
    'installation': 2400000,
    'cost_subtotal': 19312752,
    'grand_total': 22789047,
}


class PricingEngineTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_data')

    def test_matches_prototype_default_quote(self):
        partner = Partner.objects.get(code='starmas')
        result = compute_for_partner(partner, DEFAULT_LINES, margin_pct=18)
        for key, expected in EXPECTED.items():
            self.assertEqual(js_round(result[key]), expected, msg=f'{key} mismatch')

    def test_kg_partner_applies_finish_factor_to_profiles_only(self):
        partner = Partner.objects.get(code='starmas')
        line = {'product': 'fixed', 'width': 1000, 'height': 1000, 'qty': 1,
                'glass': 'clear6', 'finish': 'wood'}  # wood factor = 1.15
        result = compute_for_partner(partner, [line], margin_pct=0)
        parts = {p['key']: p for p in result['lines'][0]['parts']}
        # perimeter = 4 m; fixed kg_per_m = 1.5 -> 6 kg * 72000 * 1.15
        self.assertEqual(js_round(parts['profiles']['price']), js_round(6 * 72000 * 1.15))
        # kit parts never take the finish factor: screws 0.05 * 4 * 72000
        self.assertEqual(js_round(parts['screws']['price']), js_round(0.05 * 4 * 72000))

    def test_unit_partner_uses_factory_price_and_flat_kit(self):
        partner = Partner.objects.get(code='tostem')
        line = {'product': 'sliding2', 'width': 1000, 'height': 1000, 'qty': 1,
                'glass': 'clear6', 'finish': 'pcBlack'}  # pcBlack factor = 1.04
        result = compute_for_partner(partner, [line], margin_pct=0)
        parts = {p['key']: p for p in result['lines'][0]['parts']}
        self.assertEqual(js_round(parts['profiles']['price']), js_round(5200000 * 1.04))
        self.assertEqual(js_round(parts['rollers']['price']), 320000)  # flat per-set, no factor


class AuthTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_data')

    def test_quotes_require_authentication(self):
        resp = self.client.get('/api/quotes/')
        self.assertIn(resp.status_code, (401, 403))

    def test_login_then_me(self):
        resp = self.client.post('/api/auth/login/', {'username': 'sales', 'password': 'salesdemo123'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['authenticated'])
        me = self.client.get('/api/auth/me/')
        self.assertEqual(me.data['user']['username'], 'sales')

    def test_bad_login_rejected(self):
        resp = self.client.post('/api/auth/login/', {'username': 'sales', 'password': 'wrong'})
        self.assertEqual(resp.status_code, 400)


class QuoteSnapshotTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_data')
        cls.user = get_user_model().objects.get(username='sales')

    def setUp(self):
        self.client.force_authenticate(self.user)

    def _payload(self):
        return {'partner': 'starmas', 'margin_pct': 18, 'client_name': 'PT Test',
                'lines': DEFAULT_LINES}

    def test_compute_endpoint_matches_engine(self):
        resp = self.client.post('/api/compute/', self._payload(), format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(js_round(resp.data['grand_total']), EXPECTED['grand_total'])

    def test_create_persists_owner_and_snapshot(self):
        resp = self.client.post('/api/quotes/', self._payload(), format='json')
        self.assertEqual(resp.status_code, 201)
        quote = Quote.objects.get(pk=resp.data['id'])
        self.assertEqual(quote.owner, self.user)
        self.assertEqual(js_round(float(quote.grand_total)), EXPECTED['grand_total'])
        self.assertEqual(quote.install_days, 2)
        self.assertEqual(quote.lines.count(), 2)
        self.assertTrue(quote.reference.startswith('Q-'))
        self.assertIsNotNone(quote.valid_until)
        # the breakdown snapshot is preserved on each line
        self.assertTrue(len(quote.lines.first().parts) > 0)

    def test_snapshot_is_immutable_after_rate_change(self):
        resp = self.client.post('/api/quotes/', self._payload(), format='json')
        original_total = Decimal(resp.data['grand_total'])
        # An admin bumps service rates afterwards...
        sr = ServiceRates.load()
        sr.assembly_per_opening = Decimal('999999')
        sr.save()
        # ...the existing quote must not change.
        quote = Quote.objects.get(pk=resp.data['id'])
        self.assertEqual(quote.grand_total, original_total)

    def test_quotes_are_scoped_to_owner(self):
        self.client.post('/api/quotes/', self._payload(), format='json')
        other = get_user_model().objects.create_user('other', password='x')
        self.client.force_authenticate(other)
        resp = self.client.get('/api/quotes/')
        self.assertEqual(len(resp.data), 0)
