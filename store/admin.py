from django.contrib import admin, messages
from django.db import transaction
from django.utils.html import format_html

from .models import (
    Cart, CartItem, Category, ContactInquiry, Order, OrderItem, Product, ProductGallery,
)


# --- PRODUCT GALLERY ---
class ProductGalleryInline(admin.TabularInline):
    model = ProductGallery
    extra = 1  # Shows one blank row by default for a new image


# --- CATEGORY ---
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    # Automatically fills out the slug field based on the category name
    prepopulated_fields = {'slug': ('name',)}


# --- PRODUCT ---
class StockStatusFilter(admin.SimpleListFilter):
    """Sidebar filter: In stock / Low stock / Out of stock."""
    title = 'stock status'
    parameter_name = 'stock_status'

    def lookups(self, request, model_admin):
        return [
            ('in', 'In stock'),
            ('low', f'Low stock (1-{Product.LOW_STOCK_THRESHOLD})'),
            ('out', 'Out of stock'),
        ]

    def queryset(self, request, queryset):
        if self.value() == 'in':
            return queryset.filter(stock__gt=0)
        if self.value() == 'low':
            return queryset.filter(stock__gt=0, stock__lte=Product.LOW_STOCK_THRESHOLD)
        if self.value() == 'out':
            return queryset.filter(stock=0)
        return queryset


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['title', 'sku', 'mrp', 'price', 'stock', 'stock_status', 'created']
    list_filter = [StockStatusFilter, 'category']
    # Quick-edit prices and stock straight from the list page
    list_editable = ['mrp', 'price', 'stock']
    search_fields = ['title', 'sku']
    inlines = [ProductGalleryInline]
    fields = ['category', 'title', 'sku', 'description', 'mrp', 'price', 'stock', 'image']

    @admin.display(description='Status', ordering='stock')
    def stock_status(self, obj):
        if obj.stock <= 0:
            return format_html('<b style="color:{};">{}</b>', '#c0392b', 'Out of stock')
        if obj.is_low_stock:
            return format_html('<b style="color:{};">Low ({})</b>', '#d68910', obj.stock)
        return format_html('<span style="color:{};">{}</span>', '#1e8449', 'In stock')


# --- CART ---
admin.site.register(Cart)
admin.site.register(CartItem)


# --- ORDERS & CHECKOUT ---
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    # Shows the exact items bought. Read-only so receipts cannot be accidentally altered.
    readonly_fields = ['product', 'price', 'quantity']
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'status', 'get_total_items', 'get_purchased_skus', 'full_name', 'mobile_number',
        'email', 'shipping_address', 'city', 'postal_code', 'amount_paid',
        'payment_method', 'is_paid', 'tracking_number',
    ]
    list_editable = ['status', 'is_paid', 'tracking_number']
    date_hierarchy = 'date_ordered'
    list_filter = ['status', 'is_paid', 'payment_method', 'city']
    search_fields = ['full_name', 'email', 'mobile_number', 'shipping_address', 'id', 'tracking_number']
    inlines = [OrderItemInline]
    actions = ['mark_confirmed', 'mark_shipped', 'mark_delivered', 'cancel_and_restore_stock']

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('items__product')

    @admin.display(description='Total Items')
    def get_total_items(self, obj):
        # Order.items is the related_name defined on OrderItem.order
        return sum(item.quantity for item in obj.items.all())

    @admin.display(description='Purchased Products (SKU)')
    def get_purchased_skus(self, obj):
        return ", ".join(f"{item.product.title} (SKU: {item.product.sku})" for item in obj.items.all())

    # --- Stock is returned automatically whenever an order becomes Cancelled ---
    def save_model(self, request, obj, form, change):
        old_status = Order.objects.filter(pk=obj.pk).values_list('status', flat=True).first() if change else None
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            if old_status and old_status != 'CANCELLED' and obj.status == 'CANCELLED':
                obj.restore_stock()
                self.message_user(request, f"Order #{obj.pk} cancelled and stock restored.", messages.SUCCESS)
            elif old_status == 'CANCELLED' and obj.status != 'CANCELLED':
                self.message_user(
                    request,
                    f"Order #{obj.pk} was re-opened. Stock was NOT deducted again - adjust it manually if needed.",
                    messages.WARNING,
                )

    @admin.action(description='Mark selected orders as Confirmed')
    def mark_confirmed(self, request, queryset):
        queryset.exclude(status='CANCELLED').update(status='CONFIRMED')

    @admin.action(description='Mark selected orders as Shipped')
    def mark_shipped(self, request, queryset):
        queryset.exclude(status='CANCELLED').update(status='SHIPPED')

    @admin.action(description='Mark selected orders as Delivered')
    def mark_delivered(self, request, queryset):
        queryset.exclude(status='CANCELLED').update(status='DELIVERED')

    @admin.action(description='Cancel selected orders and restore stock')
    def cancel_and_restore_stock(self, request, queryset):
        count = 0
        with transaction.atomic():
            for order in queryset.exclude(status='CANCELLED'):
                order.restore_stock()
                order.status = 'CANCELLED'
                order.save(update_fields=['status'])
                count += 1
        self.message_user(request, f"{count} order(s) cancelled and stock restored.", messages.SUCCESS)


# --- CONTACT INQUIRIES ---
@admin.register(ContactInquiry)
class ContactInquiryAdmin(admin.ModelAdmin):
    list_display = ['name', 'subject', 'email', 'created_at']
    search_fields = ['name', 'email', 'subject']

    # Read-only so you don't accidentally edit a customer's original message
    readonly_fields = ['name', 'email', 'subject', 'message', 'created_at']