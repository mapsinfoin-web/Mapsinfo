# Generated manually for Product specifications and cross-sell
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0032_contactinquiry_phone'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='weight_grams',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Weight in grams (e.g. 12.50). Critical for customer confidence with earrings and chokers.',
                max_digits=6,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='product',
            name='dimensions',
            field=models.CharField(
                blank=True,
                default='',
                help_text="Dimensions string (e.g. 'Length: 5.2 cm | Width: 2.1 cm' or 'Drop: 45 cm (Adjustable)')",
                max_length=150,
            ),
        ),
        migrations.AddField(
            model_name='product',
            name='closure_type',
            field=models.CharField(
                blank=True,
                default='',
                help_text="Fastening type (e.g. 'Push-back stud', 'Lobster clasp', 'Adjustable cord / Dori', 'Openable cuff')",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name='product',
            name='pair_with',
            field=models.ManyToManyField(
                blank=True,
                help_text="Optional 1-2 curated matching pieces to feature in 'Complete The Look' on the PDP.",
                related_name='paired_by',
                to='store.product',
            ),
        ),
    ]
