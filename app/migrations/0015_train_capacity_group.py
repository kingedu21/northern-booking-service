from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0014_drop_orphan_smsdeliverylog_table"),
    ]

    operations = [
        migrations.AddField(
            model_name="train",
            name="capacity_group",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Optional shared seat-capacity group key for duplicate trip rows.",
                max_length=64,
                null=True,
            ),
        ),
    ]
