import django.db.models.deletion
from django.db import migrations, models

# Denmark/Norway support + welcome emails as a library:
#
# * OnboardingProfile.country / OnboardingAssignment.country (default DK).
# * FlowStep.title_no / description_no — Norwegian text, blank = use the
#   primary (Danish) text.
# * WelcomeEmailTemplate is no longer one-per-flow: it gets a name, a
#   language and a per-language is_default, and the flow link is dropped.
#   Existing templates become Danish templates named after their flow; the
#   old "default fallback" becomes the Danish default (or, if there was
#   none and exactly one template exists, that one).
# * OnboardingAssignment.welcome_email_template — the template picked in
#   the assign dialog.


def templates_forwards(apps, schema_editor):
    WelcomeEmailTemplate = apps.get_model("onboarding", "WelcomeEmailTemplate")
    rows = list(WelcomeEmailTemplate.objects.select_related("flow"))
    for t in rows:
        t.name = (t.flow.name if t.flow_id else "") or "Velkomstmail"
        t.language = "da"
        t.is_default = bool(t.is_default_fallback)
    if rows and not any(t.is_default for t in rows) and len(rows) == 1:
        rows[0].is_default = True
    if rows:
        WelcomeEmailTemplate.objects.bulk_update(rows, ["name", "language", "is_default"])


def templates_backwards(apps, schema_editor):
    # The per-flow link can't be reconstructed meaningfully; leave as-is.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0008_calendar_meeting_participants"),
    ]

    operations = [
        migrations.AddField(
            model_name="onboardingprofile",
            name="country",
            field=models.CharField(
                choices=[("DK", "Danmark"), ("NO", "Norge")],
                default="DK",
                help_text="Country the employee works in. Decides the language of their onboarding (welcome email, meeting titles) and which public holidays meeting booking skips.",
                max_length=2,
            ),
        ),
        migrations.AddField(
            model_name="onboardingassignment",
            name="country",
            field=models.CharField(
                choices=[("DK", "Danmark"), ("NO", "Norge")],
                default="DK",
                help_text="Snapshot of the employee's country at attach time — decides language and public holidays for this onboarding.",
                max_length=2,
            ),
        ),
        migrations.AddField(
            model_name="flowstep",
            name="title_no",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="flowstep",
            name="description_no",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="welcomeemailtemplate",
            name="name",
            field=models.CharField(default="", max_length=128),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="welcomeemailtemplate",
            name="language",
            field=models.CharField(
                choices=[("da", "Dansk"), ("no", "Norsk")], default="da", max_length=2
            ),
        ),
        migrations.AddField(
            model_name="welcomeemailtemplate",
            name="is_default",
            field=models.BooleanField(
                default=False,
                help_text="Preselected for new assignments in this language. Only one template per language can be the default.",
            ),
        ),
        migrations.RunPython(templates_forwards, templates_backwards),
        migrations.RemoveField(model_name="welcomeemailtemplate", name="flow"),
        migrations.RemoveField(model_name="welcomeemailtemplate", name="is_default_fallback"),
        migrations.AlterModelOptions(
            name="welcomeemailtemplate",
            options={"ordering": ["language", "name"]},
        ),
        migrations.AddField(
            model_name="onboardingassignment",
            name="welcome_email_template",
            field=models.ForeignKey(
                blank=True,
                help_text="Welcome email chosen in the assign dialog. Empty means the default template for the assignment's language.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="onboarding.welcomeemailtemplate",
            ),
        ),
    ]
