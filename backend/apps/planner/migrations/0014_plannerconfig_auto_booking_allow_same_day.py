from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("planner", "0013_managerprofile_auto_booking_periods_ahead"),
    ]

    operations = [
        migrations.AddField(
            model_name="plannerconfig",
            name="auto_booking_allow_same_day",
            field=models.BooleanField(default=False),
        ),
    ]
