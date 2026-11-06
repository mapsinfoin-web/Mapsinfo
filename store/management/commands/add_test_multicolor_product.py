import os
from django.core.management.base import BaseCommand
from django.core.files import File
from store.models import Category, Product, ProductColor


class Command(BaseCommand):
    help = 'Creates a test product with multiple color options (Amazon/Flipkart style)'

    def handle(self, *args, **kwargs):
        # 1. Get or create a category
        category = Category.objects.filter(slug='earrings').first()
        if not category:
            category = Category.objects.first()
        if not category:
            category = Category.objects.create(name='Earrings', slug='earrings')

        # 2. Create the test product
        title = "Aura Multi-Colour Crystal Chandelier Earrings"
        product, created = Product.objects.get_or_create(
            title=title,
            defaults={
                'category': category,
                'description': (
                    "Exquisite handcrafted multi-colour statement jewelry with high-grade anti-tarnish coating. "
                    "Features brilliant cut stones and safe daily wear protection. "
                    "Available in multiple luxury colour tones for weddings, evening wear, and festive celebrations."
                ),
                'mrp': 2499.00,
                'price': 1299.00,
                'stock': 30,
                'is_active': True,
            }
        )
        if not created:
            product.category = category
            product.mrp = 2499.00
            product.price = 1299.00
            product.stock = 30
            product.is_active = True
            product.save()

        # Attach sample image if product doesn't have one
        if not product.image:
            sample_img_path = os.path.join('store', 'static', '1.png')
            if os.path.exists(sample_img_path):
                with open(sample_img_path, 'rb') as f:
                    product.image.save('test_multicolor_main.png', File(f), save=True)

        # 3. Create colour options
        colors_data = [
            {'name': 'Rose Gold', 'hex_code': '#B76E79'},
            {'name': 'Yellow Gold', 'hex_code': '#D4AF37'},
            {'name': 'Silver Platinum', 'hex_code': '#C0C0C0'},
            {'name': 'Emerald Green', 'hex_code': '#046307'},
        ]

        # Refresh colors for this test product
        ProductColor.objects.filter(product=product).delete()

        created_colors = []
        for c in colors_data:
            color_obj = ProductColor.objects.create(
                product=product,
                name=c['name'],
                hex_code=c['hex_code'],
                is_available=True
            )
            created_colors.append(color_obj)

        self.stdout.write(self.style.SUCCESS(
            f"Successfully {'created' if created else 'updated'} test multi-colour product:\n"
            f" - Title: {product.title}\n"
            f" - ID: {product.pk}\n"
            f" - SKU: {product.sku}\n"
            f" - Price: Rs.{product.price} (MRP: Rs.{product.mrp})\n"
            f" - Colours added ({len(created_colors)}): {', '.join([c.name for c in created_colors])}\n"
            f" - Product URL: /product/{product.pk}/\n"
            f" - Admin URL: /admin/store/product/{product.pk}/change/"
        ))
