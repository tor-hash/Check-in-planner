from django.db import migrations

# The onboarding flow's "calendar_meeting" steps were authored with a
# literal placeholder e-mail — "manager@blackcapitaltechnology.com" —
# picked via the flow editor's "Bestemt e-mail …" (custom) option, intended
# to mean "the employee's manager". That address doesn't correspond to any
# real Django user account, so every booking attempt for these steps fails
# with "No user account found for organizer 'manager@blackcapitaltechnology.com'."
#
# Per product clarification, "manager" here is the same concept as "leder"
# (leder = the employee's manager in this system), and the intent was
# exactly the built-in default: fall back to the employee's leder. So this
# swaps the literal placeholder for the "leder" role sentinel
# (components.CalendarMeetingComponent.LEDER_SENTINEL), which resolves
# per-employee at booking time to whichever leder is on record for the
# assignment — see calendar_booking._resolve_organizer.

PLACEHOLDER_EMAIL = "manager@blackcapitaltechnology.com"
LEDER_SENTINEL = "leder"


def fix_placeholder_organizer(apps, schema_editor):
    FlowStep = apps.get_model("onboarding", "FlowStep")
    steps = FlowStep.objects.filter(
        component_type="calendar_meeting",
    )
    changed = []
    for step in steps:
        config = step.config or {}
        if (config.get("with_email") or "").strip().lower() == PLACEHOLDER_EMAIL:
            config["with_email"] = LEDER_SENTINEL
            step.config = config
            changed.append(step)
    if changed:
        FlowStep.objects.bulk_update(changed, ["config"])


def noop_reverse(apps, schema_editor):
    # Not reversible in a meaningful way — the original placeholder value
    # isn't worth restoring. Left as a no-op so the migration can still be
    # unapplied without erroring.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0004_onboardingassignment_leder_email_and_more"),
    ]

    operations = [
        migrations.RunPython(fix_placeholder_organizer, noop_reverse),
    ]
