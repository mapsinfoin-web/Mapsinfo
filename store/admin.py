from django import forms
from django.core.exceptions import ValidationError
from django.contrib import admin, messages
from django.urls import reverse
from django.db import transaction
from django.db.models import Q
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from urllib.parse import quote

from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    BogoOffer, Cart, CartGift, CartItem, Category, ContactInquiry, Notification, Order, OrderItem, PaymentSettings,
    Product, ProductColor, ProductGallery, Profile,
)


# --- PRODUCT GALLERY & COLORS ---
class ProductGalleryInline(admin.TabularInline):
    model = ProductGallery
    extra = 2
    fields = ['image', 'color']

    def formfield_for_foreign_key(self, db_field, request, **kwargs):
        if db_field.name == "color":
            try:
                from django.urls import resolve
                resolved = resolve(request.path_info)
                product_id = resolved.kwargs.get('object_id')
                if product_id:
                    kwargs["queryset"] = ProductColor.objects.filter(product_id=product_id)
            except Exception:
                pass
        return super().formfield_for_foreign_key(db_field, request, **kwargs)


class ProductColorInline(admin.TabularInline):
    model = ProductColor
    extra = 1
    fields = ['order', 'name', 'sku', 'price', 'mrp', 'hex_code', 'image', 'is_available']
    ordering = ['order', 'id']


class ColorGalleryInline(admin.TabularInline):
    model = ProductGallery
    extra = 2
    fields = ['image']
    verbose_name = 'Additional Picture for this Colour'
    verbose_name_plural = 'Additional Pictures for this Colour'


@admin.register(ProductColor)
class ProductColorAdmin(admin.ModelAdmin):
    list_display = ['product', 'order', 'name', 'sku', 'price', 'mrp', 'hex_code', 'is_available']
    list_editable = ['order', 'sku', 'price', 'mrp', 'is_available']
    list_filter = ['is_available', 'product__category']
    search_fields = ['name', 'sku', 'product__title', 'product__sku']
    ordering = ['product', 'order', 'id']
    inlines = [ColorGalleryInline]

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, ProductGallery):
                instance.product = form.instance.product
                instance.color = form.instance
            instance.save()
        formset.save_m2m()


# --- CATEGORY ---
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'parent', 'slug', 'keywords', 'order', 'product_count']
    list_filter = ['parent']
    list_editable = ['parent', 'order']
    search_fields = ['name', 'slug', 'keywords']
    # Automatically fills out the slug field based on the category name
    prepopulated_fields = {'slug': ('name',)}

    @admin.display(description='Active Products')
    def product_count(self, obj):
        direct = obj.products.filter(is_active=True).count()
        tagged = obj.tagged_products.filter(is_active=True).count()
        return direct + tagged


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
    list_display = ['title', 'sku', 'category', 'mrp', 'price', 'stock', 'stock_status', 'is_active', 'bogo_offer_names', 'created']
    list_filter = [StockStatusFilter, 'category', 'is_active']
    # Quick-edit prices and stock straight from the list page
    list_editable = ['mrp', 'price', 'stock', 'is_active']
    search_fields = ['title', 'sku']
    filter_horizontal = ['sub_categories']
    inlines = [ProductGalleryInline, ProductColorInline]
    fields = ['category', 'sub_categories', 'title', 'sku', 'description', 'mrp', 'price', 'stock', 'image', 'is_active']

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('bogo_offers')

    @admin.display(description='Free gift offer')
    def bogo_offer_names(self, obj):
        offers = list(obj.bogo_offers.all())
        if not offers:
            # One click: opens the offer form with this product already selected as the main product
            return format_html('<a href="{}?main_product={}">+ Set up free gift</a>',
                               reverse('admin:store_bogooffer_add'), obj.pk)
        return format_html_join(
            ', ', '<a href="{}">{} ({})</a>',
            ((reverse('admin:store_bogooffer_change', args=[o.pk]), o.name, o.status()) for o in offers))

    @admin.display(description='Status', ordering='stock')
    def stock_status(self, obj):
        if obj.stock <= 0:
            return format_html('<b style="color:{};">{}</b>', '#c0392b', 'Out of stock')
        if obj.is_low_stock:
            return format_html('<b style="color:{};">Low ({})</b>', '#d68910', obj.stock)
        return format_html('<span style="color:{};">{}</span>', '#1e8449', 'In stock')

    def get_inline_instances(self, request, obj=None):
        try:
            from django.db import connection
            tables = connection.introspection.table_names()
        except Exception:
            tables = []

        inline_instances = []
        for inline_class in self.inlines:
            inline = inline_class(self.model, self.admin_site)
            # If a model's table has not been created yet in the database, don't crash the change form
            if tables and inline.model._meta.db_table not in tables:
                continue
            inline_instances.append(inline)
        return inline_instances

    def change_view(self, request, object_id, form_url='', extra_context=None):
        try:
            from django.db import connection
            tables = connection.introspection.table_names()
            if tables and ProductColor._meta.db_table not in tables:
                messages.warning(
                    request,
                    "Note: Product colour options table is pending migration. "
                    "Run 'python manage.py migrate' in your terminal to enable colour variants."
                )
        except Exception:
            pass
        return super().change_view(request, object_id, form_url, extra_context)


# --- BOGO OFFERS ---
class BogoOfferForm(forms.ModelForm):
    class Meta:
        model = BogoOffer
        fields = '__all__'

    def clean(self):
        cleaned = super().clean()
        main = cleaned.get('main_product')
        free = cleaned.get('free_products')
        if free is not None and not free:
            self.add_error('free_products', 'Select at least one free product.')
        if main and free and main in free:
            self.add_error('free_products', 'The main product cannot also be its own free gift.')
        return cleaned


@admin.register(BogoOffer)
class BogoOfferAdmin(admin.ModelAdmin):
    """Pick the paid product and exactly which products the customer may choose for free."""
    form = BogoOfferForm
    list_display = ['name', 'main_product_price', 'gift_choices', 'offer_status', 'start_date', 'end_date',
                    'orders_using_offer', 'is_active']
    list_editable = ['is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'main_product__title', 'main_product__sku', 'free_products__title']
    # Searchable boxes: type a product name to find it (much easier than the two-pane list)
    autocomplete_fields = ['main_product', 'free_products']
    readonly_fields = ['usage_report']
    actions = ['enable_offers', 'disable_offers']
    fieldsets = (
        (None, {
            'fields': ('main_product', 'free_products', 'is_active'),
            'description': '<b>Step 1:</b> choose the product the customer BUYS. '
                           '<b>Step 2:</b> choose the product(s) they can pick as a FREE gift. '
                           '<b>Step 3:</b> Save. That is all.',
        }),
        ('More options (optional)', {
            'fields': ('name', 'free_per_main', 'max_free_per_order', 'start_date', 'end_date'),
            'classes': ('collapse',),
        }),
        ('Orders using this offer', {'fields': ('usage_report',), 'classes': ('collapse',)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('main_product').prefetch_related('free_products', 'order_items')

    @admin.display(description='Main product (price)')
    def main_product_price(self, obj):
        return f"{obj.main_product.title} - \u20b9{obj.main_product.price}"

    @admin.display(description='Free gift choices (price)')
    def gift_choices(self, obj):
        return ', '.join(f"{p.title} (\u20b9{p.price})" for p in obj.free_products.all()) or '-'

    @admin.display(description='Status')
    def offer_status(self, obj):
        status = obj.status()
        colour = {'Live': '#1e8449', 'Scheduled': '#2874a6'}.get(status, '#c0392b')
        return format_html('<b style="color:{};">{}</b>', colour, status)

    @admin.display(description='Orders')
    def orders_using_offer(self, obj):
        return len({item.order_id for item in obj.order_items.all()})

    @admin.display(description='Recent orders and the free gift chosen')
    def usage_report(self, obj):
        if not obj.pk:
            return 'Save the offer first.'
        gifts = obj.order_items.select_related('product', 'order').order_by('-order_id')[:25]
        if not gifts:
            return 'No orders have used this offer yet.'
        rows = format_html_join(
            '', '<tr><td style="padding:2px 12px 2px 0;"><a href="{}">Order #{}</a></td>'
                '<td style="padding:2px 12px 2px 0;">{}</td><td>{} x {}</td></tr>',
            ((reverse('admin:store_order_change', args=[g.order_id]), g.order_id,
              g.order.full_name, g.quantity, g.product.title) for g in gifts))
        return format_html('<table><tr><th align="left">Order</th><th align="left">Customer</th>'
                           '<th align="left">Free gift chosen</th></tr>{}</table>', rows)

    @admin.action(description='Turn ON selected offers')
    def enable_offers(self, request, queryset):
        done = 0
        for offer in queryset:
            offer.is_active = True
            try:
                offer.clean()   # only one active offer per main product
            except ValidationError as exc:
                self.message_user(request, f'"{offer.name}": {"; ".join(exc.messages)}', messages.ERROR)
                continue
            offer.save()
            done += 1
        if done:
            self.message_user(request, f"{done} offer(s) turned on.", messages.SUCCESS)

    @admin.action(description='Turn OFF selected offers')
    def disable_offers(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=False)} offer(s) turned off.", messages.SUCCESS)


# --- CART (Registered below with full abandoned cart tracking & WhatsApp follow-up) ---


# --- ORDERS & CHECKOUT ---
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    # Shows the exact items bought. Read-only so receipts cannot be accidentally altered.
    readonly_fields = ['product', 'price', 'quantity', 'is_free_gift', 'bogo_offer']
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class PaymentStatusFilter(admin.SimpleListFilter):
    """Sidebar filter to find the orders whose payment screenshot you still have to check."""
    title = 'payment'
    parameter_name = 'pay'

    def lookups(self, request, model_admin):
        return [
            ('verify', 'Screenshot uploaded - CHECK NOW'),
            ('await', 'Awaiting payment (no screenshot)'),
            ('paid', 'Paid'),
        ]

    def queryset(self, request, queryset):
        has_shot = ~Q(payment_screenshot='') & Q(payment_screenshot__isnull=False)
        open_orders = queryset.exclude(status='CANCELLED').filter(is_paid=False)
        if self.value() == 'verify':
            return open_orders.filter(has_shot)
        if self.value() == 'await':
            return open_orders.exclude(has_shot)
        if self.value() == 'paid':
            return queryset.filter(is_paid=True)
        return queryset


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    ordering = ['-id']   # newest order first
    list_display = [
        'id', 'status', 'get_total_items', 'get_purchased_skus', 'full_name', 'mobile_number',
        'email', 'shipping_address', 'city', 'postal_code', 'discount_amount', 'amount_paid',
        'payment_status', 'screenshot_link', 'is_paid', 'tracking_number', 'whatsapp_customer_action',
    ]
    list_editable = ['status', 'is_paid', 'tracking_number']
    date_hierarchy = 'date_ordered'
    list_filter = [PaymentStatusFilter, 'status', 'is_paid', 'city']
    search_fields = ['full_name', 'email', 'mobile_number', 'shipping_address', 'id', 'tracking_number']
    inlines = [OrderItemInline]
    readonly_fields = ['discount_amount', 'offers_applied', 'screenshot_preview', 'payment_submitted_at', 'whatsapp_customer_action']
    actions = ['mark_payment_verified', 'mark_confirmed', 'mark_shipped', 'mark_delivered', 'cancel_and_restore_stock']

    @admin.display(description='WhatsApp Customer')
    def whatsapp_customer_action(self, obj):
        if not obj or not obj.pk:
            return '-'
        digits = ''.join(ch for ch in (obj.mobile_number or '') if ch.isdigit())
        if not digits:
            return mark_safe('<span style="color:#94a3b8;">No mobile</span>')
        phone = '91' + digits if len(digits) == 10 else digits

        if obj.status == 'SHIPPED':
            if obj.tracking_number:
                msg = (
                    f"Hi {obj.full_name}, great news! ✨\n"
                    f"Your MAPSKART order #{obj.pk} has been shipped! 🚀\n\n"
                    f"📦 Tracking Details: {obj.tracking_number}\n\n"
                    f"Your jewellery is on its way. Thank you for shopping with MAPSKART! 💎"
                )
                btn_text = "📦 Send Tracking"
                bg = "#059669"
            else:
                msg = (
                    f"Hi {obj.full_name}, your MAPSKART order #{obj.pk} has been dispatched! 🚀\n"
                    f"We will share the tracking number shortly."
                )
                btn_text = "🚚 Send Shipped"
                bg = "#0284c7"
        elif obj.is_paid:
            msg = (
                f"Hi {obj.full_name}, thank you! 🎉\n"
                f"Your payment of Rs.{obj.amount_paid} for MAPSKART order #{obj.pk} has been verified.\n\n"
                f"We are packing your jewellery with care. We will update you as soon as it ships! ✨"
            )
            btn_text = "✅ Send Paid Confirm"
            bg = "#16a34a"
        else:
            msg = (
                f"Hi {obj.full_name}, this is MAPSKART regarding your order #{obj.pk} (Total: Rs.{obj.amount_paid}).\n"
                f"Please let us know if you need any assistance completing your payment screenshot upload."
            )
            btn_text = "💬 WhatsApp"
            bg = "#25D366"

        link = f"https://wa.me/{phone}?text={quote(msg)}"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener" style="'
            'background:{};color:#fff;padding:5px 10px;border-radius:4px;font-weight:600;'
            'font-size:12px;text-decoration:none;display:inline-flex;align-items:center;gap:4px;white-space:nowrap;'
            'box-shadow:0 1px 3px rgba(0,0,0,0.12);">'
            '{}</a>',
            link, bg, btn_text
        )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('items__product')

    @admin.display(description='Payment')
    def payment_status(self, obj):
        colour = {'Paid': '#1e8449', 'Payment under verification': '#d68910', 'Cancelled': '#7f8c8d'}.get(
            obj.payment_status, '#c0392b')
        return format_html('<b style="color:{};">{}</b>', colour, obj.payment_status)

    @admin.display(description='Screenshot')
    def screenshot_link(self, obj):
        if not obj.payment_screenshot:
            return '-'
        return format_html('<a href="{}" target="_blank">View</a>', obj.payment_screenshot.url)

    @admin.display(description='Payment screenshot')
    def screenshot_preview(self, obj):
        if not obj.payment_screenshot:
            return 'Customer has not uploaded a screenshot yet.'
        return format_html('<a href="{0}" target="_blank"><img src="{0}" style="max-height:360px;border-radius:8px;"></a>',
                           obj.payment_screenshot.url)

    @admin.display(description='Total Items')
    def get_total_items(self, obj):
        # Order.items is the related_name defined on OrderItem.order
        return sum(item.quantity for item in obj.items.all())

    @admin.display(description='Purchased Products (SKU)')
    def get_purchased_skus(self, obj):
        return ", ".join(
            f"{item.product.title} (SKU: {item.product.sku})" + (" [FREE GIFT]" if item.is_free_gift else "")
            for item in obj.items.all())

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

    @admin.action(description='Payment verified: mark as Paid and Confirmed')
    def mark_payment_verified(self, request, queryset):
        count = queryset.exclude(status='CANCELLED').update(is_paid=True, status='CONFIRMED')
        self.message_user(request, f"{count} order(s) marked as paid and confirmed.", messages.SUCCESS)

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
    list_display = ['name', 'phone', 'email', 'subject', 'created_at']
    search_fields = ['name', 'phone', 'email', 'subject']

    # Read-only so you don't accidentally edit a customer's original message
    readonly_fields = ['name', 'phone', 'email', 'subject', 'message', 'created_at']

# --- PAYMENT SETTINGS (Paytm QR, WhatsApp number) ---
@admin.register(PaymentSettings)
class PaymentSettingsAdmin(admin.ModelAdmin):
    """One page only: upload your Paytm QR and set the WhatsApp number that receives orders."""
    fieldsets = (
        ('Paytm QR code', {'fields': ('paytm_qr', 'payee_name', 'upi_id')}),
        ('Where customers send their order + screenshot', {'fields': ('vendor_whatsapp',)}),
        ('Optional', {'fields': ('extra_instructions',)}),
    )

    def has_add_permission(self, request):
        return not PaymentSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

# --- CART & ABANDONED CART TRACKING ---

class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    fields = ['product_preview', 'product', 'quantity', 'unit_price', 'subtotal_display', 'is_active']
    readonly_fields = ['product_preview', 'unit_price', 'subtotal_display']

    @admin.display(description='Preview')
    def product_preview(self, obj):
        if obj.product and obj.product.image:
            return format_html(
                '<img src="{}" style="width:40px;height:40px;object-fit:cover;border-radius:6px;" />',
                obj.product.image.url
            )
        return "-"

    @admin.display(description='Unit Price')
    def unit_price(self, obj):
        return f"₹{obj.product.price}" if obj.product else "-"

    @admin.display(description='Subtotal')
    def subtotal_display(self, obj):
        return f"₹{obj.sub_total()}" if obj.product else "-"


class CartGiftInline(admin.TabularInline):
    model = CartGift
    extra = 0
    fields = ['product', 'offer', 'quantity']
    readonly_fields = ['product', 'offer', 'quantity']


class CartStatusFilter(admin.SimpleListFilter):
    title = 'Cart Status'
    parameter_name = 'cart_status'

    def lookups(self, request, model_admin):
        return [
            ('abandoned', '🔴 Abandoned (Unpurchased with items)'),
            ('abandoned_phone', '💬 Abandoned with Phone (WhatsApp ready)'),
            ('abandoned_email', '✉️ Abandoned with Email'),
            ('purchased', '🟢 Purchased (Converted to Order)'),
            ('empty', '⚪ Empty Cart'),
        ]

    def queryset(self, request, queryset):
        val = self.value()
        if val == 'abandoned':
            return queryset.filter(is_purchased=False, cartitem__isnull=False).distinct()
        if val == 'abandoned_phone':
            return queryset.filter(is_purchased=False, cartitem__isnull=False).exclude(customer_phone='').distinct()
        if val == 'abandoned_email':
            return queryset.filter(is_purchased=False, cartitem__isnull=False).exclude(customer_email='').distinct()
        if val == 'purchased':
            return queryset.filter(is_purchased=True)
        if val == 'empty':
            return queryset.filter(cartitem__isnull=True)
        return queryset


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = [
        'status_badge',
        'customer_display',
        'contact_display',
        'products_preview',
        'total_items_col',
        'total_value_col',
        'followup_actions',
        'updated_at',
    ]
    list_filter = [CartStatusFilter, 'is_purchased', 'updated_at', 'date_added']
    search_fields = [
        'customer_name', 'customer_phone', 'customer_email',
        'user__username', 'user__first_name', 'user__last_name', 'user__email',
        'cartitem__product__title', 'cart_id',
    ]
    readonly_fields = [
        'cart_id', 'date_added', 'updated_at', 'status_badge',
        'customer_display', 'whatsapp_followup_button', 'total_cart_value_display',
    ]
    inlines = [CartItemInline, CartGiftInline]
    date_hierarchy = 'updated_at'

    fieldsets = (
        ('Customer Details', {
            'fields': ('user', 'customer_name', 'customer_email', 'customer_phone', 'whatsapp_followup_button')
        }),
        ('Cart State & Value', {
            'fields': ('status_badge', 'is_purchased', 'order', 'total_cart_value_display')
        }),
        ('Technical Data', {
            'fields': ('cart_id', 'date_added', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'order').prefetch_related(
            'cartitem_set__product', 'gifts__product'
        )

    @admin.display(description='Status')
    def status_badge(self, obj):
        if obj.is_purchased:
            if obj.order_id:
                order_url = reverse('admin:store_order_change', args=[obj.order_id])
                return format_html(
                    '<a href="{}" style="background:#e6f4ea;color:#137333;padding:4px 8px;border-radius:999px;font-weight:600;text-decoration:none;font-size:11px;">'
                    '🟢 Order #{}</a>',
                    order_url, obj.order_id
                )
            return mark_safe(
                '<span style="background:#e6f4ea;color:#137333;padding:4px 8px;border-radius:999px;font-weight:600;font-size:11px;">'
                '🟢 Purchased</span>'
            )
        
        items_count = obj.total_items()
        if items_count > 0:
            return mark_safe(
                '<span style="background:#fce8e6;color:#c5221f;padding:4px 8px;border-radius:999px;font-weight:700;font-size:11px;">'
                '🔴 Abandoned Cart</span>'
            )
        return mark_safe(
            '<span style="background:#f1f3f4;color:#5f6368;padding:4px 8px;border-radius:999px;font-size:11px;">'
            '⚪ Empty</span>'
        )

    @admin.display(description='Customer')
    def customer_display(self, obj):
        name = obj.customer_name
        if obj.user:
            user_url = reverse('admin:auth_user_change', args=[obj.user_id])
            username_part = mark_safe(f'<a href="{user_url}"><b>{obj.user.username}</b></a>')
            if name and name.lower() != obj.user.username.lower():
                return mark_safe(f'{username_part} <span style="color:#5f6368;">({name})</span>')
            return username_part
        if name:
            return format_html('<b>{}</b> <span style="font-size:11px;color:#888;">(Guest)</span>', name)
        return format_html('<span style="color:#888;">Guest ({})</span>', obj.cart_id[:8] if obj.cart_id else "No ID")

    @admin.display(description='Contact')
    def contact_display(self, obj):
        parts = []
        if obj.customer_phone:
            parts.append(format_html('📞 <b>{}</b>', obj.customer_phone))
        if obj.customer_email:
            parts.append(format_html('✉️ <a href="mailto:{}">{}</a>', obj.customer_email, obj.customer_email))
        elif obj.user and obj.user.email:
            parts.append(format_html('✉️ <a href="mailto:{}">{}</a>', obj.user.email, obj.user.email))
        
        if not parts:
            return mark_safe('<span style="color:#999;font-style:italic;">No contact info</span>')
        return mark_safe(f'<div style="line-height:1.4;">{"<br>".join(parts)}</div>')

    @admin.display(description='Products in Cart')
    def products_preview(self, obj):
        items = list(obj.cartitem_set.select_related('product'))
        if not items:
            return mark_safe('<span style="color:#888;">No items</span>')
        
        preview_html = []
        for item in items[:3]:
            if item.product and item.product.image:
                img_tag = f'<img src="{item.product.image.url}" style="width:28px;height:28px;object-fit:cover;border-radius:4px;vertical-align:middle;margin-right:6px;" />'
            else:
                img_tag = '<span style="display:inline-block;width:28px;height:28px;background:#eee;border-radius:4px;vertical-align:middle;margin-right:6px;"></span>'
            preview_html.append(f'<div>{img_tag}<span>{item.quantity}x {item.product.title}</span></div>')
        
        if len(items) > 3:
            preview_html.append(f'<div style="color:#888;font-size:11px;">+{len(items) - 3} more</div>')
            
        return mark_safe(f'<div style="display:flex;flex-direction:column;gap:4px;">{"".join(preview_html)}</div>')

    @admin.display(description='Items')
    def total_items_col(self, obj):
        return obj.total_items()

    @admin.display(description='Cart Value')
    def total_value_col(self, obj):
        val = obj.total_value()
        return format_html('<b>₹{}</b>', val)

    @admin.display(description='Quick Follow-Up')
    def followup_actions(self, obj):
        buttons = []
        phone = (obj.customer_phone or '').strip()
        name = obj.customer_name or (obj.user.get_full_name() or obj.user.username if obj.user else 'there')
        summary = obj.product_summary()

        if phone:
            clean_phone = ''.join(ch for ch in phone if ch.isdigit())
            if len(clean_phone) == 10:
                clean_phone = '91' + clean_phone
            
            msg = (
                f"Hi {name}, we noticed you were looking at {summary} on MAPSKART! "
                f"We wanted to check if you had any questions about the product, quality, or delivery? "
                f"We would be delighted to assist you!"
            )
            wa_url = f"https://wa.me/{clean_phone}?text={quote(msg)}"
            buttons.append(
                format_html(
                    '<a href="{}" target="_blank" style="background:#25D366;color:#ffffff;padding:5px 10px;'
                    'border-radius:6px;font-weight:700;font-size:11.5px;text-decoration:none;'
                    'display:inline-flex;align-items:center;gap:4px;white-space:nowrap;box-shadow:0 1px 3px rgba(0,0,0,0.15);">'
                    '💬 WhatsApp</a>',
                    wa_url
                )
            )

        email = obj.customer_email or (obj.user.email if obj.user else '')
        if email:
            email_body = (
                f"Hi {name},\n\n"
                f"We noticed you added {summary} to your shopping cart at MAPSKART.\n\n"
                f"Please let us know if you need help completing your order or have questions about our products.\n\n"
                f"Best regards,\nMAPSKART Team"
            )
            mail_url = f"mailto:{email}?subject={quote('Your MAPSKART Shopping Bag')}&body={quote(email_body)}"
            buttons.append(
                format_html(
                    '<a href="{}" style="background:#1a73e8;color:#ffffff;padding:5px 10px;'
                    'border-radius:6px;font-weight:700;font-size:11.5px;text-decoration:none;'
                    'display:inline-flex;align-items:center;gap:4px;white-space:nowrap;">'
                    '✉️ Email</a>',
                    mail_url
                )
            )

        if not buttons:
            return mark_safe('<span style="color:#aaa;font-size:11px;">No contact</span>')
        return mark_safe(f'<div style="display:flex;gap:6px;align-items:center;">{"".join(buttons)}</div>')

    @admin.display(description='WhatsApp Follow-Up')
    def whatsapp_followup_button(self, obj):
        phone = (obj.customer_phone or '').strip()
        if not phone:
            return mark_safe('<span style="color:#888;">No phone number provided yet</span>')
        
        name = obj.customer_name or (obj.user.get_full_name() or obj.user.username if obj.user else 'Customer')
        summary = obj.product_summary()
        clean_phone = ''.join(ch for ch in phone if ch.isdigit())
        if len(clean_phone) == 10:
            clean_phone = '91' + clean_phone

        msg = (
            f"Hi {name}, we noticed you were looking at {summary} on MAPSKART! "
            f"We wanted to check if you had any questions about the product, quality, or delivery? "
            f"We would be delighted to assist you!"
        )
        wa_url = f"https://wa.me/{clean_phone}?text={quote(msg)}"
        return format_html(
            '<a href="{}" target="_blank" style="background:#25D366;color:#ffffff;padding:8px 16px;'
            'border-radius:8px;font-weight:700;font-size:13px;text-decoration:none;'
            'display:inline-flex;align-items:center;gap:8px;box-shadow:0 2px 4px rgba(0,0,0,0.15);">'
            '💬 Open WhatsApp Chat with Customer ({})</a>',
            wa_url, phone
        )

    @admin.display(description='Total Cart Value')
    def total_cart_value_display(self, obj):
        return f"₹{obj.total_value()} ({obj.total_items()} items)"


# --- NOTIFICATIONS & ANNOUNCEMENTS ---
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['title', 'type_badge', 'is_active', 'show_in_announcement_bar', 'destination_preview', 'created_at']
    list_filter = ['notification_type', 'is_active', 'show_in_announcement_bar', 'created_at']
    list_editable = ['is_active', 'show_in_announcement_bar']
    search_fields = ['title', 'message', 'badge_text']
    autocomplete_fields = ['product']
    fieldsets = (
        ('Notification Content', {
            'fields': ('title', 'message', 'notification_type', 'badge_text')
        }),
        ('Link Destination (Optional)', {
            'fields': ('product', 'category', 'link_url', 'link_text'),
            'description': 'Choose a product or collection to auto-generate the link, or specify a custom URL.'
        }),
        ('Visibility Settings', {
            'fields': ('is_active', 'show_in_announcement_bar'),
            'description': 'Active notifications appear in the header notification bell. Check "show in announcement bar" to also scroll in the top ticker.'
        }),
    )

    @admin.display(description='Type', ordering='notification_type')
    def type_badge(self, obj):
        styles = {
            'restock': ('#059669', '#d1fae5', '🔄 Restock'),
            'collection': ('#1d4ed8', '#dbeafe', '✨ New Collection'),
            'sale': ('#dc2626', '#fee2e2', '🔥 Sale / Offer'),
            'info': ('#4b5563', '#f3f4f6', '📢 Announcement'),
        }
        color, bg, label = styles.get(obj.notification_type, ('#1F3A66', '#e0f2fe', obj.notification_type))
        return format_html(
            '<span style="background:{}; color:{}; padding:4px 9px; border-radius:12px; font-weight:700; font-size:11.5px; display:inline-block;">{}</span>',
            bg, color, label
        )

    @admin.display(description='Target Link')
    def destination_preview(self, obj):
        url = obj.get_target_url()
        if not url:
            return mark_safe('<span style="color:#9ca3af; font-size:12px;">None</span>')
        return format_html('<a href="{}" target="_blank" style="font-weight:600; text-decoration:underline;">{} ↗</a>', url, obj.link_text or 'View')


# --- CUSTOMER USER ADMIN WITH PHONE NUMBER PROFILE ---
class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = 'Customer Mobile & Profile'
    fields = ['phone_number']

try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline]
    list_display = ['username', 'email', 'get_phone', 'first_name', 'last_name', 'is_staff']
    search_fields = ['username', 'email', 'first_name', 'last_name', 'profile__phone_number']

    @admin.display(description='Mobile Number')
    def get_phone(self, obj):
        profile = getattr(obj, 'profile', None)
        return profile.phone_number if profile and profile.phone_number else '-'


