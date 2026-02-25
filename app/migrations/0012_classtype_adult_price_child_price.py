from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0011_trainclasscapacity_seatallocation_class_type_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='classtype',
            name='adult_price',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='classtype',
            name='child_price',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
    ]
