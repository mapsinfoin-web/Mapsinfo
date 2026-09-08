from django.contrib import admin
from .models import Category, Product, Cart, CartItem, ProductGallery, Order, OrderItem, ContactInquiry

# --- PRODUCT GALLERY ---
class ProductGalleryInline(admin.TabularInline):
    model = ProductGallery
    extra = 1 # Shows one blank row by default for a new image

# --- CATEGORY ---
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    # Automatically fills out the slug field based on the category name
    prepopulated_fields = {'slug': ('name',)}

# --- PRODUCT ---
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    # Now shows the SKU in the product list
    list_display = ['title', 'sku', 'price', 'in_stock', 'created']
    # Adds a filter sidebar
    list_filter = ['in_stock', 'category']
    # Allows you to edit these fields directly from the list view
    list_editable = ['price', 'in_stock']
    # Adds a search bar to easily find products by Name or SKU
    search_fields = ['title', 'sku']
    # Attach the gallery inline to this product view
    inlines = [ProductGalleryInline]
    # Controls field order/visibility on the add/edit form - sku shown right after title
    fields = ['category', 'title', 'sku', 'description', 'price', 'image', 'in_stock']

# --- CART ---
# Register your Cart models so you can view them in the admin panel too
admin.site.register(Cart)
admin.site.register(CartItem)

# --- ORDERS & CHECKOUT ---
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    # Shows the exact items bought. Read-only so receipts cannot be accidentally altered.
    readonly_fields = ['product', 'price', 'quantity']

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'get_total_items', 'get_purchased_skus', 'full_name', 'mobile_number', 'email', 'shipping_address', 'city', 'postal_code', 'amount_paid', 'payment_method', 'is_paid']

    list_editable = ['is_paid']
    date_hierarchy = 'date_ordered'
    list_filter = ['is_paid', 'payment_method', 'city']
    search_fields = ['full_name', 'email', 'mobile_number', 'shipping_address', 'id']
    inlines = [OrderItemInline]

    @admin.display(description='Total Items')
    def get_total_items(self, obj):
        # Order.items is the related_name defined on OrderItem.order
        return sum(item.quantity for item in obj.items.all())

    @admin.display(description='Purchased Products (SKU)')
    def get_purchased_skus(self, obj):
        items = obj.items.all()
        return ", ".join([f"{item.product.title} (SKU: {item.product.sku})" for item in items])

# --- CONTACT INQUIRIES ---
@admin.register(ContactInquiry)
class ContactInquiryAdmin(admin.ModelAdmin):
    list_display = ['name', 'subject', 'email', 'created_at']
    search_fields = ['name', 'email', 'subject']

    # We make these read-only so you don't accidentally edit a customer's original message!
    readonly_fields = ['name', 'email', 'subject', 'message', 'created_at']