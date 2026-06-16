# Generated manually for calendar share requests

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("planner", "0004_plannerconfig_weeks_per_session"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CalendarShareRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sent_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("channel", models.CharField(default="email", max_length=16)),
                ("success", models.BooleanField(default=False)),
                ("error_message", models.TextField(blank=True, default="")),
                (
                    "person",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="calendar_share_requests",
                        to="planner.person",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="calendar_share_requests_sent",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-sent_at"],
            },
        ),
        migrations.AddIndex(
            model_name="calendarsharerequest",
            index=models.Index(
                fields=["person", "requested_by", "-sent_at"],
                name="planner_cal_person__a1b2c3_idx",
            ),
        ),
    ]
