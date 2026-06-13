from django.contrib import admin

from .models import (
    Finish,
    GlassType,
    KitComponent,
    Partner,
    PriceList,
    Product,
    ProductKit,
    ProductUnitPrice,
    Quote,
    QuoteLine,
    ServiceRates,
)


class ProductUnitPriceInline(admin.TabularInline):
    model = ProductUnitPrice
    extra = 0


@admin.register(PriceList)
class PriceListAdmin(admin.ModelAdmin):
    list_display = ['partner', 'version', 'effective_date', 'is_current', 'rate_per_kg']
    list_filter = ['partner', 'is_current']
    inlines = [ProductUnitPriceInline]


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'basis', 'sort_order']


class ProductKitInline(admin.TabularInline):
    model = ProductKit
    extra = 0
    autocomplete_fields = ['component']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name_en', 'code', 'kg_per_m', 'glass_factor', 'sort_order']
    inlines = [ProductKitInline]


@admin.register(KitComponent)
class KitComponentAdmin(admin.ModelAdmin):
    list_display = ['name_en', 'code', 'kg_per_m', 'unit_price']
    search_fields = ['code', 'name_en', 'name_id']


@admin.register(GlassType)
class GlassTypeAdmin(admin.ModelAdmin):
    list_display = ['name_en', 'code', 'rate', 'sort_order']


@admin.register(Finish)
class FinishAdmin(admin.ModelAdmin):
    list_display = ['name_en', 'code', 'factor', 'sort_order']


@admin.register(ServiceRates)
class ServiceRatesAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'assembly_per_opening', 'logistics_flat',
                    'install_per_day', 'units_per_install_day']

    def has_add_permission(self, request):
        # Singleton — edit the one row, never add another.
        return not ServiceRates.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class QuoteLineInline(admin.TabularInline):
    model = QuoteLine
    extra = 0
    readonly_fields = ['product', 'product_name_en', 'glass', 'finish', 'width', 'height',
                       'qty', 'per_unit_price', 'small_parts_per_unit', 'line_total']
    can_delete = False


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
    list_display = ['reference', 'client_name', 'owner', 'partner', 'grand_total',
                    'valid_until', 'created_at']
    list_filter = ['partner', 'owner']
    search_fields = ['reference', 'client_name']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [QuoteLineInline]
