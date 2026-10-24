import uuid

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F


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

    def save(self, *args, **kwargs):
        if not self.sku:
            self.sku = uuid.uuid4().hex[:8].upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} (ID: {self.sku})"

class Cart(models.Model):
    cart_id = models.CharField(max_length=250, blank=True)
    date_added = models.DateField(auto_now_add=True)

    def __str__(self):
        return self.cart_id


class CartItem(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)

    def sub_total(self):
        return self.product.price * self.quantity

    def __str__(self):
        return self.product.title


class ProductGallery(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='gallery_images')
    image = models.ImageField(upload_to='images/gallery/', max_length=255)

    def __str__(self):
        return f"Image for {self.product.title}"

    class Meta:
        verbose_name = 'Product Gallery'
        verbose_name_plural = 'Product Galleries'


class Order(models.Model):
    PAYMENT_CHOICES = (
        ('COD', 'Cash on Delivery'),
        ('PHONEPE', 'PhonePe UPI'),
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

    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='COD')
    is_paid = models.BooleanField(default=False,
                                  help_text="Check this when PhonePe payment is verified or COD is collected.")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    tracking_number = models.CharField(max_length=100, blank=True)

    date_ordered = models.DateTimeField(auto_now_add=True)

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
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField(default=1, validators=[MinValueValidator(1)])

    def __str__(self):
        return f'{self.quantity} x {self.product.title}'


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