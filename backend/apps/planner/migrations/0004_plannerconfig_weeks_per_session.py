from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("planner", "0003_journalentryfile"),
    ]

    operations = [
        migrations.AddField(
            model_name="plannerconfig",
            name="weeks_per_session",
            field=models.PositiveSmallIntegerField(default=2),
        ),
    ]
