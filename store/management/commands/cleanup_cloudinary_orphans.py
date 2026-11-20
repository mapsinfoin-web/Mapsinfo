from django.core.management.base import BaseCommand
from django.conf import settings
import cloudinary
import cloudinary.api
import cloudinary.uploader
from store.models import Product, ProductColor, ProductGallery, ProductReview, PaymentSettings, Order


class Command(BaseCommand):
    help = "Find and delete orphaned images from Cloudinary that are no longer referenced in the database."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='List orphaned images without actually deleting them from Cloudinary.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        # Ensure Cloudinary SDK is initialized with credentials
        c_conf = getattr(settings, 'CLOUDINARY_STORAGE', {})
        cloudinary.config(
            cloud_name=c_conf.get('CLOUD_NAME'),
            api_key=c_conf.get('API_KEY'),
            api_secret=c_conf.get('API_SECRET')
        )

        self.stdout.write("Collecting all active image paths from database...")
        active_db_names = set()

        for m, field in [
            (Product, 'image'),
            (ProductColor, 'image'),
            (ProductGallery, 'image'),
            (ProductReview, 'image'),
            (PaymentSettings, 'paytm_qr'),
            (Order, 'payment_screenshot'),
        ]:
            names = m.objects.exclude(**{field: ''}).exclude(**{f"{field}__isnull": True}).values_list(field, flat=True)
            for n in names:
                if n:
                    clean = str(n).strip()
                    active_db_names.add(clean)

        self.stdout.write(f"Found {len(active_db_names)} active image references in the database.")

        self.stdout.write("Scanning Cloudinary for images under 'media/images/'...")
        orphans = []
        next_cursor = None

        while True:
            kwargs = {'type': 'upload', 'prefix': 'media/images/', 'max_results': 100}
            if next_cursor:
                kwargs['next_cursor'] = next_cursor

            try:
                res = cloudinary.api.resources(**kwargs)
            except Exception as e:
                self.stderr.write(f"Failed to query Cloudinary API: {e}")
                return

            resources = res.get('resources', [])
            for r in resources:
                pid = r.get('public_id')
                if pid and pid not in active_db_names:
                    orphans.append(r)

            next_cursor = res.get('next_cursor')
            if not next_cursor:
                break

        if not orphans:
            self.stdout.write(self.style.SUCCESS("No orphaned images found in Cloudinary! All images are actively linked."))
            return

        self.stdout.write(f"Found {len(orphans)} orphaned image(s) in Cloudinary.")

        deleted_count = 0
        total_bytes = 0
        for item in orphans:
            pid = item.get('public_id')
            size = item.get('bytes', 0)
            total_bytes += size
            if dry_run:
                self.stdout.write(f"  [DRY-RUN] Would delete: {pid} ({size} bytes)")
            else:
                try:
                    resp = cloudinary.uploader.destroy(pid, invalidate=True)
                    if resp.get('result') == 'ok':
                        deleted_count += 1
                        self.stdout.write(f"  [DELETED] {pid}")
                    else:
                        self.stdout.write(f"  [SKIPPED] {pid} ({resp.get('result')})")
                except Exception as exc:
                    self.stderr.write(f"  [ERROR] Could not delete {pid}: {exc}")

        if dry_run:
            self.stdout.write(self.style.WARNING(f"\n[DRY-RUN COMPLETE] {len(orphans)} orphaned images ({round(total_bytes / (1024 * 1024), 2)} MB) found. Run without --dry-run to purge."))
        else:
            self.stdout.write(self.style.SUCCESS(f"\n[PURGE COMPLETE] Successfully deleted {deleted_count} orphaned images from Cloudinary."))
