import re
import uuid

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F
from django.utils import timezone


class Category(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)

    class Meta:
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, related_name='products', on_delete=models.PROTECT)
    title = models.CharField(max_length=255)
    sku = models.CharField(max_length=50, unique=True, blank=True, null=True, help_text="Unique Product ID")
    description = models.TextField(blank=True)
    mrp = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True,
                              help_text="Original Retail Price (crossed out)")
    price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Current Sale Price")
    image = models.ImageField(upload_to='images/', blank=True, null=True)

    # Single source of truth for availability. "In stock" is computed from this number.
    stock = models.PositiveIntegerField(default=10, help_text="Units available. 0 = Out of Stock")

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, help_text="Uncheck to hide this product from the store.")

    # ADD THE META CLASS HERE:
    class Meta:
        ordering = ['-created']

    # Show a "Only X left" warning when stock is at or below this number
    LOW_STOCK_THRESHOLD = 5

    @property
    def in_stock(self):
        return self.stock > 0

    @property
    def is_low_stock(self):
        return 0 < self.stock <= self.LOW_STOCK_THRESHOLD

    @property
    def discount_percent(self):
        """Returns the percentage discount if mrp > price, rounded to whole number (e.g. 20)."""
        if self.mrp and self.mrp > self.price and self.mrp > 0:
            return round(((self.mrp - self.price) / self.mrp) * 100)
        return 0

    @property
    def discount_amount(self):
        """Returns the amount saved in rupees."""
        if self.mrp and self.mrp > self.price:
            return self.mrp - self.price
        return 0

    @property
    def available_colors(self):
        """Returns active colors for this product if defined, otherwise empty list."""
        if hasattr(self, '_prefetched_objects_cache') and 'colors' in self._prefetched_objects_cache:
            colors = [c for c in self.colors.all() if c.is_available]
            return sorted(colors, key=lambda c: (c.order, c.id))
        try:
            return list(self.colors.filter(is_available=True).order_by('order', 'id'))
        except Exception:
            return []

    @property
    def packaging_text(self):
        """Returns custom packaging text: velvet jewellery box for earrings, velvet jewellery pouch for necklaces & others."""
        cat_slug = (self.category.slug.lower() if self.category and self.category.slug else '')
        title_lower = (self.title.lower() if self.title else '')
        if 'earring' in cat_slug or 'earring' in title_lower:
            return 'Includes velvet jewellery box'
        return 'Includes velvet jewellery pouch'

    @property
    def color_tags(self):
        """Returns normalized list of lowercase color slugs associated with this product."""
        if hasattr(self, '_cached_color_tags'):
            return self._cached_color_tags
        palette = ['blue', 'pink', 'green', 'purple', 'crystal', 'white', 'yellow', 'gold', 'black', 'multicolour', 'ruby', 'silver']
        tags = set()
        for c in self.available_colors:
            s = c.name.strip().lower()
            if s in ['yello', 'yellow']:
                tags.add('yellow')
            else:
                tags.add(s)
        t = (self.title or '').lower()
        import re
        for p in palette:
            if re.search(r'\b' + p + r'\b', t):
                tags.add(p)
        self._cached_color_tags = sorted(list(tags))
        return self._cached_color_tags

    @property
    def color_tags_str(self):
        """Space-separated list for data-colors attribute."""
        return " ".join(self.color_tags)

    @property
    def color_images_json(self):
        """JSON mapping of color slug -> image url for instant frontend image switching."""
        if hasattr(self, '_cached_color_images_json'):
            return self._cached_color_images_json
        import json
        cmap = {}
        for c in self.available_colors:
            s = c.name.strip().lower()
            if s in ['yello', 'yellow']:
                s = 'yellow'
            if c.image:
                cmap[s] = c.image.url
        default_img = self.image.url if self.image else ''
        for tag in self.color_tags:
            if tag not in cmap and default_img:
                cmap[tag] = default_img
        self._cached_color_images_json = json.dumps(cmap)
        return self._cached_color_images_json

    def save(self, *args, **kwargs):
        if not self.sku:
            self.sku = uuid.uuid4().hex[:8].upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} (ID: {self.sku})"


class BogoOffer(models.Model):
    """
    Buy One Get One Free, controlled by the admin.
    The admin picks ONE paid "main" product and the exact free gifts the customer may choose from.
    Nothing becomes free unless it is listed here.
    """
    name = models.CharField(max_length=120, blank=True,
                            help_text="Optional. Leave empty and it is named automatically.")
    is_active = models.BooleanField(default=True, help_text="Master switch. Untick to turn the offer off immediately.")
    main_product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='bogo_offers', verbose_name='Main product (paid)',
        help_text="The product the customer must buy to qualify.")
    free_products = models.ManyToManyField(
        Product, related_name='free_gift_offers', verbose_name='Free products (gift choices)',
        help_text="The customer picks from these. Only the products you select here can ever be free.")
    free_per_main = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1)], verbose_name='Free gifts per main product',
        help_text="Buying 2 units of the main product gives 2 gifts when this is 1.")
    max_free_per_order = models.PositiveIntegerField(
        null=True, blank=True, help_text="Most free gifts one order can get from this offer. Empty = no limit.")
    start_date = models.DateTimeField(null=True, blank=True, help_text="Leave empty to start immediately.")
    end_date = models.DateTimeField(null=True, blank=True, help_text="Leave empty for no end date.")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']
        verbose_name = 'BOGO Offer'
        verbose_name_plural = 'BOGO Offers'

    def clean(self):
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValidationError({'end_date': 'End date must be after the start date.'})
        if self.is_active and self.main_product_id:
            clash = BogoOffer.objects.filter(main_product_id=self.main_product_id, is_active=True).exclude(pk=self.pk)
            if clash.exists():
                raise ValidationError({'main_product': f'"{clash.first().name}" is already an active offer for this '
                                                       f'product. Switch it off first or edit that one.'})

    def save(self, *args, **kwargs):
        if not self.name:
            self.name = f"{self.main_product.title} + free gift"
        super().save(*args, **kwargs)

    @property
    def badge_text(self):
        return "Buy 1 Get 1 Free"

    @property
    def headline(self):
        return f"Buy this {self.main_product.title} & get a free gift!"

    def status(self, now=None):
        now = now or timezone.now()
        if not self.is_active:
            return 'Disabled'
        if self.start_date and now < self.start_date:
            return 'Scheduled'
        if self.end_date and now > self.end_date:
            return 'Expired'
        return 'Live'

    def is_live(self, now=None):
        return self.status(now) == 'Live'

    def __str__(self):
        return f"{self.name} ({self.main_product.title})"


class Cart(models.Model):
    cart_id = models.CharField(max_length=250, blank=True)
    date_added = models.DateField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Customer & user details for admin follow-up
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='carts')
    customer_name = models.CharField(max_length=200, blank=True, default='', help_text="Customer name for follow-up")
    customer_email = models.CharField(max_length=200, blank=True, default='', help_text="Customer email for follow-up")
    customer_phone = models.CharField(max_length=30, blank=True, default='', help_text="Mobile number for follow-up")

    # Purchase state
    is_purchased = models.BooleanField(default=False, help_text="True if order was completed, False if abandoned/active")
    order = models.ForeignKey('Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='source_carts')

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Cart / Abandoned Cart'
        verbose_name_plural = 'Carts & Abandoned Follow-Ups'

    def __str__(self):
        user_info = self.customer_name or (self.user.username if self.user else f"Guest ({self.cart_id[:8]})")
        return f"Cart #{self.pk} - {user_info}"

    def total_items(self):
        qs = self.cartitem_set.filter(is_active=True) if not self.is_purchased else self.cartitem_set.all()
        return sum(item.quantity for item in qs)

    def total_value(self):
        qs = self.cartitem_set.filter(is_active=True) if not self.is_purchased else self.cartitem_set.all()
        return sum(item.sub_total() for item in qs)

    def product_summary(self):
        items = list(self.cartitem_set.select_related('product'))
        if not items:
            return "Empty"
        return ", ".join(f"{item.quantity}x {item.product.title}" for item in items[:3])


class CartItem(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)

    @property
    def unit_price(self):
        """Returns the price for the selected colour variant if defined, else product base price."""
        if hasattr(self, 'selected_color') and self.selected_color:
            color_obj = self.product.colors.filter(name__iexact=self.selected_color).first()
            if color_obj and color_obj.price is not None:
                return color_obj.price
        return self.product.price

    def sub_total(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return self.product.title


class CartGift(models.Model):
    """A free gift the customer picked for a BOGO offer. Always re-validated on the server."""
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='gifts')
    offer = models.ForeignKey(BogoOffer, on_delete=models.CASCADE, related_name='cart_gifts')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])

    class Meta:
        unique_together = ('cart', 'offer', 'product')

    def __str__(self):
        return f"FREE {self.product.title} x{self.quantity}"


class ProductGallery(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='gallery_images')
    color = models.ForeignKey(
        'ProductColor',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gallery_images',
        help_text="Optional: link this picture to a specific colour variant (e.g. Blue, Pink)"
    )
    image = models.ImageField(upload_to='images/gallery/', max_length=255)

    def __str__(self):
        color_str = f" [{self.color.name}]" if self.color else ""
        return f"Image for {self.product.title}{color_str}"

    class Meta:
        verbose_name = 'Product Gallery'
        verbose_name_plural = 'Product Galleries'


class ProductColor(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='colors')
    order = models.PositiveIntegerField(
        default=0,
        help_text="Position / display order (e.g. 1 for first, 2 for second, 3 for third)"
    )
    name = models.CharField(max_length=60, help_text="Color name, e.g. Rose Gold, Yellow Gold, Silver, Emerald Green")
    sku = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text="SKU ID for this color variant (e.g. MAPS-CSE-192-BLU). Auto-generated if left empty."
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Sale price for this colour (optional; leave blank to use the product's default price)"
    )
    mrp = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Original retail price (crossed out) for this colour (optional)"
    )
    hex_code = models.CharField(max_length=20, default="#D4AF37", help_text="Hex color code for swatch dot (e.g. #D4AF37 for Gold, #C0C0C0 for Silver, #B76E79 for Rose Gold)")
    image = models.ImageField(upload_to='images/colors/', blank=True, null=True, help_text="Main / cover photo for this color variant (switches main image when selected)")
    is_available = models.BooleanField(default=True, help_text="Tick if this color is in stock")

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'Product Color Option'
        verbose_name_plural = 'Product Color Options'

    @property
    def effective_price(self):
        """Returns variant price if set, otherwise the main product price."""
        if self.price is not None:
            return self.price
        return self.product.price

    @property
    def effective_mrp(self):
        """Returns variant MRP if set, otherwise the main product MRP."""
        if self.mrp is not None:
            return self.mrp
        return self.product.mrp

    @property
    def discount_percent(self):
        """Calculates discount percentage for this variant."""
        p = self.effective_price
        m = self.effective_mrp
        if m and m > p:
            return round(((m - p) / m) * 100)
        return 0

    @property
    def all_images(self):
        """Returns all image URLs for this colour: main image + all assigned gallery images."""
        urls = []
        if self.image:
            try:
                urls.append(self.image.url)
            except Exception:
                pass
        for g in self.gallery_images.all():
            try:
                if g.image and g.image.url not in urls:
                    urls.append(g.image.url)
            except Exception:
                pass
        return urls

    def save(self, *args, **kwargs):
        if not self.sku:
            base = (self.product.sku if self.product and self.product.sku else "PRD").strip()
            name_clean = re.sub(r'[^A-Za-z0-9]', '', self.name or '').upper()
            common_abbr = {
                'BLUE': 'BLU', 'PINK': 'PNK', 'GREEN': 'GRN', 'CRYSTAL': 'CRYS',
                'BLACK': 'BLK', 'WHITE': 'WHT', 'RED': 'RED', 'YELLOW': 'YEL',
                'GOLD': 'GLD', 'ROSEGOLD': 'RGLD', 'SILVER': 'SLV', 'PURPLE': 'PURP',
            }
            code = common_abbr.get(name_clean, name_clean[:4] if name_clean else uuid.uuid4().hex[:4].upper())
            candidate = f"{base}-{code}"
            if ProductColor.objects.filter(sku=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{code}-{uuid.uuid4().hex[:3].upper()}"
            self.sku = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        sku_part = f" ({self.sku})" if self.sku else ""
        price_part = f" - ₹{self.price}" if self.price is not None else ""
        return f"{self.product.title} - {self.name}{sku_part}{price_part}"


class Order(models.Model):
    # New orders are always PAYTM (QR code). COD / PHONEPE stay in the list only so old orders still display.
    PAYMENT_CHOICES = (
        ('PAYTM', 'Paytm QR'),
        ('COD', 'Cash on Delivery (old orders)'),
        ('PHONEPE', 'PhonePe UPI (old orders)'),
    )

    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('CONFIRMED', 'Confirmed'),
        ('SHIPPED', 'Shipped'),
        ('DELIVERED', 'Delivered'),
        ('CANCELLED', 'Cancelled'),
    )

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    full_name = models.CharField(max_length=250)
    email = models.EmailField(max_length=250)
    mobile_number = models.CharField(max_length=20, default="")

    shipping_address = models.TextField()
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    # Offer details saved at purchase time, so history stays correct even if the offer changes later
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    offers_applied = models.JSONField(default=list, blank=True,
                                      help_text="BOGO offers used on this order: offer, main product, free gifts chosen, discount.")

    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='PAYTM')
    is_paid = models.BooleanField(default=False,
                                  help_text="Tick this after you have checked the payment screenshot and the money is in your Paytm.")
    payment_screenshot = models.ImageField(upload_to='payments/', blank=True, null=True,
                                           help_text="Uploaded by the customer after paying on Paytm.")
    payment_submitted_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    tracking_number = models.CharField(max_length=100, blank=True)

    date_ordered = models.DateTimeField(auto_now_add=True)

    @property
    def payment_status(self):
        if self.status == 'CANCELLED':
            return 'Cancelled'
        if self.is_paid:
            return 'Paid'
        if self.payment_screenshot:
            return 'Payment under verification'
        return 'Awaiting payment'

    def restore_stock(self):
        """Put every item in this order back into stock (used when an order is cancelled)."""
        for item in self.items.all():
            Product.objects.filter(pk=item.product_id).update(stock=F('stock') + item.quantity)

    def __str__(self):
        return f'Order #{self.id} - {self.full_name}'


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    # PROTECT: a product that appears in past orders can't be deleted by accident
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    color = models.CharField(max_length=60, blank=True, default="", help_text="Selected colour variant")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    # Free gifts are saved as their own line: price = 0, flagged, and linked to the offer that gave them
    is_free_gift = models.BooleanField(default=False)
    bogo_offer = models.ForeignKey(BogoOffer, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='order_items')

    def __str__(self):
        color_str = f" [{self.color}]" if self.color else ""
        return f'{self.quantity} x {self.product.title}{color_str}'


class ContactInquiry(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField()
    subject = models.CharField(max_length=255)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Inquiry from {self.name} - {self.subject}"
    
class Wishlist(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wishlist')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    added_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Prevents a user from liking the same product multiple times
        unique_together = ('user', 'product')

    def __str__(self):
        return f"{self.user.username} liked {self.product.title}"

# Orders are sent to this WhatsApp number unless a different one is saved in Admin > Payment settings
DEFAULT_VENDOR_WHATSAPP = '919953595557'
DEFAULT_UPI_ID = 'maps536969@sbi'


class PaymentSettings(models.Model):
    """The shop's Paytm details. Only ONE row; edit it in the admin under 'Payment settings'."""
    paytm_qr = models.ImageField(upload_to='payment/', blank=True, null=True, verbose_name='Paytm QR code image',
                                 help_text="Upload the QR code image from your Paytm for Business app.")
    payee_name = models.CharField(max_length=120, blank=True, default='MAPSKART', help_text="Name shown on the Paytm QR, e.g. MAPSKART.")
    upi_id = models.CharField(max_length=120, blank=True, default=DEFAULT_UPI_ID, verbose_name='UPI ID',
                              help_text="Shown under the QR code and used for one-click UPI payments, e.g. maps536969@sbi.")
    vendor_whatsapp = models.CharField(
        max_length=20, blank=True, verbose_name='Vendor WhatsApp number',
        help_text="With country code, digits only. Example for India: 919876543210. "
                  "Customers send their order details and payment screenshot link to this number.")
    extra_instructions = models.TextField(blank=True, help_text="Optional extra line shown on the payment page.")

    class Meta:
        verbose_name = 'Payment settings'
        verbose_name_plural = 'Payment settings'

    @classmethod
    def get(cls):
        return cls.objects.first()

    def get_upi_id(self):
        return (self.upi_id or '').strip() or DEFAULT_UPI_ID

    @classmethod
    def shop_upi_id(cls):
        shop = cls.get()
        return shop.get_upi_id() if shop else DEFAULT_UPI_ID

    def whatsapp_number(self):
        digits = ''.join(ch for ch in self.vendor_whatsapp if ch.isdigit())
        return digits or DEFAULT_VENDOR_WHATSAPP

    @classmethod
    def vendor_number(cls):
        """The WhatsApp number that receives orders: the admin's number, otherwise the default."""
        shop = cls.get()
        return shop.whatsapp_number() if shop else DEFAULT_VENDOR_WHATSAPP

    def __str__(self):
        return 'Payment settings'


class Notification(models.Model):
    TYPE_CHOICES = [
        ('restock', 'Restock Alert'),
        ('collection', 'New Collection'),
        ('sale', 'Special Offer / Sale'),
        ('info', 'Announcement / Update'),
    ]

    title = models.CharField(
        max_length=150,
        help_text="Headline (e.g. 'Emerald Studs Restocked!', 'New Noor Bridal Collection Live!')"
    )
    message = models.TextField(
        help_text="Detailed notification content for visitors and customers."
    )
    notification_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default='restock',
        verbose_name="Type"
    )
    badge_text = models.CharField(
        max_length=40,
        blank=True,
        help_text="Optional custom badge text (e.g. 'RESTOCKED', 'NEW DROP', 'LIMITED'). Defaults based on type if empty."
    )

    # Optional destination targets
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Optional: link directly to a specific product."
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Optional: link directly to a collection."
    )
    link_url = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional custom URL (e.g. /sale/ or external URL). Overrides product/category."
    )
    link_text = models.CharField(
        max_length=50,
        blank=True,
        default="View Now",
        help_text="Button text (e.g. 'Shop Restock', 'Explore Collection', 'Shop Sale')."
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Turn ON to publish immediately to customers on the website."
    )
    show_in_announcement_bar = models.BooleanField(
        default=False,
        help_text="Also feature this notification in the scrolling announcement bar at the top."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'

    def __str__(self):
        return f"[{self.get_notification_type_display()}] {self.title}"

    @property
    def display_badge(self):
        if self.badge_text:
            return self.badge_text
        defaults = {
            'restock': 'RESTOCKED',
            'collection': 'NEW COLLECTION',
            'sale': 'SPECIAL OFFER',
            'info': 'ANNOUNCEMENT',
        }
        return defaults.get(self.notification_type, 'UPDATE')

    def get_target_url(self):
        if self.link_url:
            return self.link_url
        if self.product:
            from django.urls import reverse
            return reverse('store:product_detail', args=[self.product.pk])
        if self.category:
            from django.urls import reverse
            return reverse('store:collection_detail', args=[self.category.slug])
        return ""


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        default='',
        verbose_name='Mobile Number',
        help_text="Customer 10-digit mobile number"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Customer Profile'
        verbose_name_plural = 'Customer Profiles'

    def __str__(self):
        return f"{self.user.username} ({self.phone_number})"

