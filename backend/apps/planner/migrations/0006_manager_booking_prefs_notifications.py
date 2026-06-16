"""Add booking preferences to ManagerProfile, declined status to CheckInMeeting,
and new ManagerNotification model."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("planner", "0005_calendarsharerequest"),
    ]

    operations = [
        # ------------------------------------------------------------------ #
        # ManagerProfile — booking preference fields                          #
        # ------------------------------------------------------------------ #
        migrations.AddField(
            model_name="managerprofile",
            name="auto_booking_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="managerprofile",
            name="booking_blocked_windows",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="managerprofile",
            name="preferred_meeting_duration_minutes",
            field=models.PositiveSmallIntegerField(default=30),
        ),
        migrations.AddField(
            model_name="managerprofile",
            name="booking_preferred_days",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="managerprofile",
            name="notification_email",
            field=models.EmailField(blank=True, default="", max_length=254),
        ),
        # ------------------------------------------------------------------ #
        # CheckInMeeting — add "declined" status choice                       #
        # (Django CharField choices are not enforced at DB level; changing    #
        #  choices only updates the Python/admin layer — no DDL needed.)      #
        # ------------------------------------------------------------------ #
        migrations.AlterField(
            model_name="checkinmeeting",
            name="status",
            field=models.CharField(
                choices=[
                    ("scheduled", "Scheduled"),
                    ("cancelled", "Cancelled"),
                    ("completed", "Completed"),
                    ("declined", "Declined by attendee"),
                ],
                default="scheduled",
                max_length=16,
            ),
        ),
        # ------------------------------------------------------------------ #
        # ManagerNotification — new model                                     #
        # ------------------------------------------------------------------ #
        migrations.CreateModel(
            name="ManagerNotification",
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
                (
                    "notification_type",
                    models.CharField(
                        choices=[
                            ("meeting_declined", "Meeting declined by attendee"),
                            ("no_slot_found", "No available slot found for auto-booking"),
                        ],
                        max_length=32,
                    ),
                ),
                ("message", models.TextField()),
                ("is_read", models.BooleanField(default=False)),
                ("email_sent", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "manager",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to="planner.managerprofile",
                    ),
                ),
                (
                    "meeting",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="notifications",
                        to="planner.checkinmeeting",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="managernotification",
            index=models.Index(
                fields=["manager", "is_read", "-created_at"],
                name="planner_mgr_notif_read_idx",
            ),
        ),
    ]
