"""Data model for the GSM CPQ tool.

Catalog entities (Partner, Product, KitComponent, GlassType, Finish) hold the
intrinsic / shared data. Partner-variable, versionable prices live on PriceList
(per-kg rate) and ProductUnitPrice (per-unit factory prices). Quote / QuoteLine
store a price *snapshot* at save time so later price-list edits never change an
existing quote.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models


class Partner(models.Model):
    KG = 'kg'
    UNIT = 'unit'
    BASIS_CHOICES = [(KG, 'Per kilogram'), (UNIT, 'Per unit')]

    code = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    basis = models.CharField(max_length=8, choices=BASIS_CHOICES)
    color_primary = models.CharField(max_length=9, default='#327EBC')
    color_secondary = models.CharField(max_length=9, default='#100E2B')
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name

    @property
    def current_price_list(self):
        return self.price_lists.filter(is_current=True).first()

    @property
    def effective_price_list(self):
        """The list used for pricing: the current one, else the most recent.

        A partner flagged "update pending" (no current list) still prices off its
        latest known list — matching the prototype, where `isCurrent` is only a
        freshness badge and never blocks pricing.
        """
        return self.current_price_list or self.price_lists.order_by('-effective_date').first()


class PriceList(models.Model):
    partner = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name='price_lists')
    version = models.CharField(max_length=16)
    effective_date = models.DateField()
    is_current = models.BooleanField(default=False)
    # Only used for kg-basis partners; null for unit partners.
    rate_per_kg = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['partner', '-effective_date']
        constraints = [
            models.UniqueConstraint(fields=['partner', 'version'], name='unique_partner_version'),
            models.UniqueConstraint(
                fields=['partner'], condition=models.Q(is_current=True),
                name='one_current_pricelist_per_partner',
            ),
        ]

    def __str__(self):
        return f'{self.partner.code} {self.version}'


class KitComponent(models.Model):
    """Small parts auto-bundled into a product (gaskets, screws, ...).

    Dual-rated: kg_per_m drives weight pricing for kg partners; unit_price is the
    flat per-set price for unit partners.
    """
    code = models.SlugField(max_length=32, unique=True)
    name_id = models.CharField(max_length=120)
    name_en = models.CharField(max_length=120)
    kg_per_m = models.DecimalField(max_digits=6, decimal_places=3)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return self.name_en


class Product(models.Model):
    code = models.SlugField(max_length=32, unique=True)
    name_id = models.CharField(max_length=120)
    name_en = models.CharField(max_length=120)
    kg_per_m = models.DecimalField(max_digits=6, decimal_places=3)        # weight per m of perimeter
    glass_factor = models.DecimalField(max_digits=4, decimal_places=3)    # glazed fraction of opening area
    kit = models.ManyToManyField(KitComponent, through='ProductKit', related_name='products')
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'code']

    def __str__(self):
        return self.name_en


class ProductKit(models.Model):
    """Ordered membership of a kit component in a product's auto-included kit."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='kit_links')
    component = models.ForeignKey(KitComponent, on_delete=models.CASCADE, related_name='product_links')
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order']
        constraints = [
            models.UniqueConstraint(fields=['product', 'component'], name='unique_product_component'),
        ]

    def __str__(self):
        return f'{self.product.code} · {self.component.code}'


class ProductUnitPrice(models.Model):
    """Factory per-unit price of a product, scoped to a (unit-basis) price list."""
    price_list = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name='product_prices')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='unit_prices')
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['price_list', 'product'], name='unique_pricelist_product'),
        ]

    def __str__(self):
        return f'{self.price_list} · {self.product.code}'


class GlassType(models.Model):
    code = models.SlugField(max_length=32, unique=True)
    name_id = models.CharField(max_length=120)
    name_en = models.CharField(max_length=120)
    rate = models.DecimalField(max_digits=12, decimal_places=2)  # per m²
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'code']

    def __str__(self):
        return self.name_en


class Finish(models.Model):
    code = models.SlugField(max_length=32, unique=True)
    name_id = models.CharField(max_length=120)
    name_en = models.CharField(max_length=120)
    factor = models.DecimalField(max_digits=4, decimal_places=3)  # price multiplier
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'code']

    def __str__(self):
        return self.name_en


class ServiceRates(models.Model):
    """Global service rates. Singleton (always pk=1)."""
    assembly_per_opening = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('350000'))
    logistics_flat = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('750000'))
    install_per_day = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('1200000'))
    units_per_install_day = models.PositiveIntegerField(default=3)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Service rates'
        verbose_name_plural = verbose_name  # singleton — singular and plural read the same

    def __str__(self):
        return self._meta.verbose_name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Quote(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='quotes')
    reference = models.CharField(max_length=24, blank=True)
    client_name = models.CharField(max_length=200)
    client_contact = models.CharField(max_length=200, blank=True)
    client_site = models.CharField(max_length=300, blank=True)
    project_type = models.CharField(max_length=8, default='0')

    # Snapshot anchors: which partner/list the prices were locked against.
    partner = models.ForeignKey(Partner, on_delete=models.PROTECT)
    price_list = models.ForeignKey(PriceList, on_delete=models.PROTECT)
    margin_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('18'))
    template_id = models.CharField(max_length=16, default='pdf')

    # Snapshot totals (frozen at save).
    materials = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    small_parts = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    assembly = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    logistics = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    installation = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    install_days = models.PositiveIntegerField(default=0)
    cost_subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    margin_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))

    valid_until = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.reference or f'Quote #{self.pk}'


class QuoteLine(models.Model):
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    product_name_id = models.CharField(max_length=120)  # snapshot of name at save
    product_name_en = models.CharField(max_length=120)
    glass = models.ForeignKey(GlassType, on_delete=models.PROTECT)
    finish = models.ForeignKey(Finish, on_delete=models.PROTECT)
    width = models.PositiveIntegerField()   # mm
    height = models.PositiveIntegerField()  # mm
    qty = models.PositiveIntegerField()

    # Snapshot pricing (frozen at save).
    per_unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    small_parts_per_unit = models.DecimalField(max_digits=14, decimal_places=2)
    line_total = models.DecimalField(max_digits=14, decimal_places=2)
    parts = models.JSONField(default=list)  # full breakdown [{key,name,basis,price,auto}]
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order']

    def __str__(self):
        return f'{self.product_name_en} ({self.width}×{self.height})'
