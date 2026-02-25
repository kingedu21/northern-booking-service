from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0009_smsdeliverylog'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='selected_seats',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.CreateModel(
            name='SeatAllocation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('travel_date', models.DateField()),
                ('seat_number', models.PositiveIntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('booking', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='seat_allocations', to='app.booking')),
                ('train', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='seat_allocations', to='app.train')),
            ],
            options={
                'ordering': ['travel_date', 'seat_number'],
            },
        ),
        migrations.AddConstraint(
            model_name='seatallocation',
            constraint=models.UniqueConstraint(fields=('train', 'travel_date', 'seat_number'), name='unique_train_date_seat'),
        ),
    ]
