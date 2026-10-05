from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("planner", "0012_rename_planner_cal_person__a1b2c3_idx_planner_cal_person__f52fc5_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="managerprofile",
            name="auto_booking_periods_ahead",
            field=models.PositiveSmallIntegerField(default=2),
        ),
    ]
