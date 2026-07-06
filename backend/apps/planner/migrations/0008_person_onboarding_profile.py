from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("onboarding", "0001_initial"),
        ("planner", "0007_bookingrunlog"),
    ]

    operations = [
        migrations.AddField(
            model_name="person",
            name="onboarding_profile",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="planner_person",
                to="onboarding.onboardingprofile",
            ),
        ),
    ]
