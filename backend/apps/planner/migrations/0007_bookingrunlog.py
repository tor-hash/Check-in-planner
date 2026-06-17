from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("planner", "0006_manager_booking_prefs_notifications"),
    ]

    operations = [
        migrations.CreateModel(
            name="BookingRunLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "triggered_by",
                    models.CharField(
                        choices=[("cron", "Cron job"), ("manual", "Manual (Run Now)")],
                        default="cron",
                        max_length=16,
                    ),
                ),
                ("meetings_created", models.PositiveIntegerField(default=0)),
                ("meetings_skipped", models.PositiveIntegerField(default=0)),
                ("errors_count", models.PositiveIntegerField(default=0)),
                ("error_detail", models.TextField(blank=True, default="")),
            ],
            options={
                "ordering": ["-started_at"],
            },
        ),
    ]
