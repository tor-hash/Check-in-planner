import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('onboarding', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='onboardingassignment',
            name='assigned_by',
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Manager/user who attached this flow. Used as the welcome "
                    "email sender and to resolve 'assigning_manager' meeting organizers."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='onboarding_assignments_made',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='onboardingassignment',
            name='welcome_email_sent_at',
            field=models.DateTimeField(
                blank=True,
                help_text=(
                    "Set once the combined welcome/calendar-share email has "
                    "been sent for this assignment. Re-attaching does not resend it."
                ),
                null=True,
            ),
        ),
    ]
