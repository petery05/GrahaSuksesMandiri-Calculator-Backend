from rest_framework import serializers

from .models import Finish, GlassType, Partner, Product, Quote, QuoteLine


# ---------- catalog (read) ----------
class PartnerSerializer(serializers.ModelSerializer):
    price_list_version = serializers.SerializerMethodField()
    price_list_updated = serializers.SerializerMethodField()
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = Partner
        fields = ['code', 'name', 'basis', 'color_primary', 'color_secondary',
                  'price_list_version', 'price_list_updated', 'is_current']

    def _list(self, obj):
        return obj.effective_price_list

    def get_price_list_version(self, obj):
        pl = self._list(obj)
        return pl.version if pl else None

    def get_price_list_updated(self, obj):
        pl = self._list(obj)
        return pl.effective_date if pl else None

    def get_is_current(self, obj):
        return obj.current_price_list is not None


class ProductSerializer(serializers.ModelSerializer):
    kit = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ['code', 'name_id', 'name_en', 'kit']

    def get_kit(self, obj):
        return [link.component.code for link in obj.kit_links.all()]


class GlassSerializer(serializers.ModelSerializer):
    class Meta:
        model = GlassType
        fields = ['code', 'name_id', 'name_en']


class FinishSerializer(serializers.ModelSerializer):
    class Meta:
        model = Finish
        fields = ['code', 'name_id', 'name_en']


# ---------- quotes (read) ----------
class QuoteLineReadSerializer(serializers.ModelSerializer):
    product = serializers.CharField(source='product.code')
    glass = serializers.CharField(source='glass.code')
    finish = serializers.CharField(source='finish.code')

    class Meta:
        model = QuoteLine
        fields = ['id', 'product', 'product_name_id', 'product_name_en', 'glass', 'finish',
                  'width', 'height', 'qty', 'per_unit_price', 'small_parts_per_unit',
                  'line_total', 'parts', 'sort_order']


class QuoteReadSerializer(serializers.ModelSerializer):
    lines = QuoteLineReadSerializer(many=True, read_only=True)
    partner = serializers.CharField(source='partner.code')
    partner_name = serializers.CharField(source='partner.name')
    price_list_version = serializers.CharField(source='price_list.version')
    owner = serializers.CharField(source='owner.username')

    class Meta:
        model = Quote
        fields = ['id', 'reference', 'owner', 'client_name', 'client_contact', 'client_site',
                  'project_type', 'partner', 'partner_name', 'price_list_version', 'margin_pct',
                  'template_id', 'materials', 'small_parts', 'assembly', 'logistics',
                  'installation', 'install_days', 'cost_subtotal', 'margin_amount', 'grand_total',
                  'valid_until', 'created_at', 'updated_at', 'lines']


# ---------- quotes / compute (write) ----------
class LineInputSerializer(serializers.Serializer):
    product = serializers.SlugField()
    glass = serializers.SlugField()
    finish = serializers.SlugField()
    width = serializers.IntegerField(min_value=1)
    height = serializers.IntegerField(min_value=1)
    qty = serializers.IntegerField(min_value=1)


class ComputeInputSerializer(serializers.Serializer):
    partner = serializers.SlugField()
    margin_pct = serializers.FloatField(default=18)
    lang = serializers.ChoiceField(choices=['id', 'en'], default='id')
    lines = LineInputSerializer(many=True)

    def validate_partner(self, value):
        if not Partner.objects.filter(code=value).exists():
            raise serializers.ValidationError(f'Unknown partner: {value}')
        return value

    def validate(self, attrs):
        _validate_line_codes(attrs['lines'])
        return attrs


class QuoteWriteSerializer(ComputeInputSerializer):
    client_name = serializers.CharField(max_length=200)
    client_contact = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    client_site = serializers.CharField(max_length=300, required=False, allow_blank=True, default='')
    project_type = serializers.CharField(max_length=8, required=False, default='0')
    template_id = serializers.CharField(max_length=16, required=False, default='pdf')


def _validate_line_codes(lines):
    if not lines:
        raise serializers.ValidationError('At least one line is required.')
    products = {ln['product'] for ln in lines}
    glasses = {ln['glass'] for ln in lines}
    finishes = {ln['finish'] for ln in lines}
    known_products = set(Product.objects.filter(code__in=products).values_list('code', flat=True))
    known_glass = set(GlassType.objects.filter(code__in=glasses).values_list('code', flat=True))
    known_finish = set(Finish.objects.filter(code__in=finishes).values_list('code', flat=True))
    missing = (
        [f'product:{c}' for c in products - known_products]
        + [f'glass:{c}' for c in glasses - known_glass]
        + [f'finish:{c}' for c in finishes - known_finish]
    )
    if missing:
        raise serializers.ValidationError({'lines': f'Unknown codes: {", ".join(missing)}'})
