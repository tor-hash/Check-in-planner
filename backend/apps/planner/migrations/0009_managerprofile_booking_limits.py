from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("planner", "0008_person_onboarding_profile"),
    ]

    operations = [
        migrations.AddField(
            model_name="managerprofile",
            name="max_auto_bookings_per_day",
            field=models.PositiveSmallIntegerField(default=2),
        ),
        migrations.AddField(
            model_name="managerprofile",
            name="booking_gap_minutes",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="managerprofile",
            name="preferred_meeting_duration_minutes",
            field=models.PositiveSmallIntegerField(default=15),
        ),
    ]
