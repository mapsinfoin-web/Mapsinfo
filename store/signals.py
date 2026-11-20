import logging
from django.db.models.signals import pre_delete, post_delete, pre_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def safe_delete_file(file_field, exclude_instance=None):
    """
    Safely delete a file from Cloudinary (or media storage).
    Verifies that no other model instance in the database is referencing the same file before destroying.
    """
    if not file_field or not getattr(file_field, 'name', None):
        return

    name = str(file_field.name).strip()
    if not name:
        return

    from store.models import Product, ProductColor, ProductGallery, ProductReview

    prod_qs = Product.objects.filter(image=name)
    color_qs = ProductColor.objects.filter(image=name)
    gallery_qs = ProductGallery.objects.filter(image=name)
    review_qs = ProductReview.objects.filter(image=name)

    if exclude_instance and getattr(exclude_instance, 'pk', None):
        if isinstance(exclude_instance, Product):
            prod_qs = prod_qs.exclude(pk=exclude_instance.pk)
            color_qs = color_qs.exclude(product_id=exclude_instance.pk)
            gallery_qs = gallery_qs.exclude(product_id=exclude_instance.pk)
        elif isinstance(exclude_instance, ProductColor):
            color_qs = color_qs.exclude(pk=exclude_instance.pk)
            gallery_qs = gallery_qs.exclude(color_id=exclude_instance.pk)
        elif isinstance(exclude_instance, ProductGallery):
            gallery_qs = gallery_qs.exclude(pk=exclude_instance.pk)
        elif isinstance(exclude_instance, ProductReview):
            review_qs = review_qs.exclude(pk=exclude_instance.pk)

    # If any other record still uses this file name, do not destroy it
    if prod_qs.exists() or color_qs.exists() or gallery_qs.exists() or review_qs.exists():
        logger.info("File %s is still in use by another database record; keeping in storage.", name)
        return

    try:
        storage = getattr(file_field, 'storage', None)
        if storage:
            storage.delete(name)
            logger.info("Successfully deleted file %s from Cloudinary storage.", name)
    except Exception as exc:
        logger.warning("Could not delete file %s from Cloudinary storage: %s", name, exc)


# ---------------------------------------------------------------------------
# PRODUCT SIGNALS
# ---------------------------------------------------------------------------
@receiver(pre_delete, sender='store.Product')
def cleanup_product_images_before_delete(sender, instance, **kwargs):
    """
    When a Product is deleted, delete:
    1. The product's main image from Cloudinary
    2. All related ProductGallery images from Cloudinary
    3. All related ProductColor images and their gallery images from Cloudinary
    """
    # 1. Product main image
    if instance.image:
        safe_delete_file(instance.image, exclude_instance=instance)

    # 2. Product gallery images
    try:
        for gallery_item in instance.gallery_images.all():
            if gallery_item.image:
                safe_delete_file(gallery_item.image, exclude_instance=instance)
    except Exception as exc:
        logger.warning("Error cleaning gallery images for product %s: %s", instance.pk, exc)

    # 3. Product color images & their gallery images
    try:
        for color_item in instance.colors.all():
            if color_item.image:
                safe_delete_file(color_item.image, exclude_instance=instance)
            for color_gallery in color_item.gallery_images.all():
                if color_gallery.image:
                    safe_delete_file(color_gallery.image, exclude_instance=instance)
    except Exception as exc:
        logger.warning("Error cleaning color images for product %s: %s", instance.pk, exc)


@receiver(pre_save, sender='store.Product')
def cleanup_old_product_image_on_update(sender, instance, **kwargs):
    """When a product's main image is replaced with a new one, delete the old file from Cloudinary."""
    if not instance.pk:
        return
    try:
        old_obj = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return
    old_file = old_obj.image
    new_file = instance.image
    if old_file and old_file.name and (not new_file or old_file.name != getattr(new_file, 'name', None)):
        safe_delete_file(old_file, exclude_instance=instance)


# ---------------------------------------------------------------------------
# PRODUCT COLOR SIGNALS
# ---------------------------------------------------------------------------
@receiver(pre_delete, sender='store.ProductColor')
def cleanup_color_image_on_delete(sender, instance, **kwargs):
    """When a ProductColor is deleted, delete its image and associated gallery images from Cloudinary."""
    if instance.image:
        safe_delete_file(instance.image, exclude_instance=instance)
    try:
        for gallery_item in instance.gallery_images.all():
            if gallery_item.image:
                safe_delete_file(gallery_item.image, exclude_instance=instance)
    except Exception as exc:
        logger.warning("Error cleaning gallery for color %s: %s", instance.pk, exc)


@receiver(pre_save, sender='store.ProductColor')
def cleanup_old_color_image_on_update(sender, instance, **kwargs):
    """When a ProductColor image is replaced, delete the old file from Cloudinary."""
    if not instance.pk:
        return
    try:
        old_obj = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return
    old_file = old_obj.image
    new_file = instance.image
    if old_file and old_file.name and (not new_file or old_file.name != getattr(new_file, 'name', None)):
        safe_delete_file(old_file, exclude_instance=instance)


# ---------------------------------------------------------------------------
# PRODUCT GALLERY SIGNALS
# ---------------------------------------------------------------------------
@receiver(post_delete, sender='store.ProductGallery')
def cleanup_gallery_image_on_delete(sender, instance, **kwargs):
    """When an individual ProductGallery record is deleted, delete its file from Cloudinary."""
    if instance.image:
        safe_delete_file(instance.image, exclude_instance=instance)


@receiver(pre_save, sender='store.ProductGallery')
def cleanup_old_gallery_image_on_update(sender, instance, **kwargs):
    """When a gallery image is replaced, delete the old file from Cloudinary."""
    if not instance.pk:
        return
    try:
        old_obj = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return
    old_file = old_obj.image
    new_file = instance.image
    if old_file and old_file.name and (not new_file or old_file.name != getattr(new_file, 'name', None)):
        safe_delete_file(old_file, exclude_instance=instance)


# ---------------------------------------------------------------------------
# PRODUCT REVIEW SIGNALS
# ---------------------------------------------------------------------------
@receiver(post_delete, sender='store.ProductReview')
def cleanup_review_image_on_delete(sender, instance, **kwargs):
    """When a review with a customer photo is deleted, delete its file from Cloudinary."""
    if instance.image:
        safe_delete_file(instance.image, exclude_instance=instance)
