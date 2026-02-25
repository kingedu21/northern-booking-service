from django.db import migrations, models
import django.db.models.deletion


def backfill_seatallocation_class_type(apps, schema_editor):
    SeatAllocation = apps.get_model('app', 'SeatAllocation')
    for allocation in SeatAllocation.objects.select_related('booking').all():
        booking = getattr(allocation, 'booking', None)
        if booking and allocation.class_type_id is None:
            allocation.class_type_id = booking.class_type_id
            allocation.save(update_fields=['class_type'])


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0010_booking_selected_seats_seatallocation'),
    ]

    operations = [
        migrations.CreateModel(
            name='TrainClassCapacity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('seat_count', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('class_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='train_capacities', to='app.classtype')),
                ('train', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='class_capacities', to='app.train')),
            ],
            options={
                'verbose_name': 'Train Class Capacity',
                'verbose_name_plural': 'Train Class Capacities',
                'ordering': ['train', 'class_type'],
            },
        ),
        migrations.AddField(
            model_name='seatallocation',
            name='class_type',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='seat_allocations', to='app.classtype'),
        ),
        migrations.AddIndex(
            model_name='seatallocation',
            index=models.Index(fields=['train'], name='seatalloc_train_idx'),
        ),
        migrations.RunPython(backfill_seatallocation_class_type, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name='seatallocation',
            name='unique_train_date_seat',
        ),
        migrations.AddConstraint(
            model_name='seatallocation',
            constraint=models.UniqueConstraint(fields=('train', 'class_type', 'travel_date', 'seat_number'), name='unique_train_class_date_seat'),
        ),
        migrations.AddConstraint(
            model_name='trainclasscapacity',
            constraint=models.UniqueConstraint(fields=('train', 'class_type'), name='unique_train_class_capacity'),
        ),
    ]
