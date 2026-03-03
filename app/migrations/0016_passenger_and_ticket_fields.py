from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0015_train_capacity_group"),
    ]

    operations = [
        migrations.CreateModel(
            name="Passenger",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("full_name", models.CharField(max_length=120)),
                ("gender", models.CharField(choices=[("Male", "Male"), ("Female", "Female"), ("Other", "Other")], default="Other", max_length=10)),
                ("age", models.PositiveIntegerField(blank=True, null=True)),
                ("seat_number", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True, blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, blank=True, null=True)),
                ("booking", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="passengers", to="app.booking")),
            ],
            options={
                "ordering": ["seat_number", "id"],
            },
        ),
        migrations.AddField(
            model_name="ticket",
            name="passenger",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="tickets", to="app.passenger"),
        ),
        migrations.AddField(
            model_name="ticket",
            name="seat_number",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ticket",
            name="ticket_uid",
            field=models.CharField(blank=True, db_index=True, max_length=32, null=True, unique=True),
        ),
        migrations.AddConstraint(
            model_name="passenger",
            constraint=models.UniqueConstraint(fields=("booking", "seat_number"), name="unique_booking_passenger_seat"),
        ),
    ]
