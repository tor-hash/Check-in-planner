from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("planner", "0009_managerprofile_booking_limits"),
    ]

    operations = [
        migrations.AddField(
            model_name="checkinmeeting",
            name="google_meet_link",
            field=models.URLField(blank=True, default=""),
        ),
    ]
