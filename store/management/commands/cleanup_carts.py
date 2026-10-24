from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from store.models import Cart

class Command(BaseCommand):
    help = 'Deletes carts that are older than 30 days'

    def handle(self, *args, **kwargs):
        # Calculate the date 30 days ago
        cutoff_date = timezone.now().date() - timedelta(days=30)
        
        # Find and delete all carts created before the cutoff
        stale_carts = Cart.objects.filter(date_added__lt=cutoff_date)
        deleted_count, _ = stale_carts.delete()
        
        self.stdout.write(self.style.SUCCESS(f'Successfully deleted {deleted_count} stale carts.'))