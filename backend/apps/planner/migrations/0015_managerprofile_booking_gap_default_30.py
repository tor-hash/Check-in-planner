from django.db import migrations, models


def bump_zero_gap_to_30(apps, schema_editor):
    """Managers still on the old default (0) get the new default (30).

    The buffer now also applies to every non-check-in event in the manager's
    calendar, and 30 minutes is the agreed default. Managers can lower it
    again (including to 0) on their booking settings page.
    """
    ManagerProfile = apps.get_model("planner", "ManagerProfile")
    ManagerProfile.objects.filter(booking_gap_minutes=0).update(booking_gap_minutes=30)


class Migration(migrations.Migration):

    dependencies = [
        ("planner", "0014_plannerconfig_auto_booking_allow_same_day"),
    ]

    operations = [
        migrations.AlterField(
            model_name="managerprofile",
            name="booking_gap_minutes",
            field=models.PositiveSmallIntegerField(default=30),
        ),
        migrations.RunPython(bump_zero_gap_to_30, migrations.RunPython.noop),
    ]
