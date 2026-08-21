from django.contrib import admin
from .models import Category, Product, Cart, CartItem, ProductGallery, Order, OrderItem

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
    # Shows full customer details directly in the main list
    list_display = ['id', 'full_name', 'email', 'city', 'amount_paid', 'date_ordered']
    
    # Creates a clickable timeline at the top (e.g., "Today", "Past 7 days", "This month")
    date_hierarchy = 'date_ordered' 
    
    list_filter = ['city']
    
    # Adds a search bar to instantly find a customer's order by their name, email, or order ID
    search_fields = ['full_name', 'email', 'shipping_address', 'id']
    
    # Attaches the purchased items directly to the Order view
    inlines = [OrderItemInline]
    
from .models import ContactInquiry # Make sure to add this to your imports at the top if you prefer!

# --- CONTACT INQUIRIES ---
@admin.register(ContactInquiry)
class ContactInquiryAdmin(admin.ModelAdmin):
    list_display = ['name', 'subject', 'email', 'created_at']
    search_fields = ['name', 'email', 'subject']
    
    # We make these read-only so you don't accidentally edit a customer's original message!
    readonly_fields = ['name', 'email', 'subject', 'message', 'created_at']