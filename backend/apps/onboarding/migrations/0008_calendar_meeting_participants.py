from django.db import migrations

# calendar_meeting steps now take a list of participants instead of a
# single organizer: config.with_email -> config.participants (see
# components.CalendarMeetingComponent.participant_tokens, which still reads
# with_email, so this is a tidy-up rather than a requirement).
#
# Steps whose title names both the leder/manager and the buddy (e.g.
# "Welcome with manager & buddy", "Meeting with Buddy and Leader") get both
# as participants (unless it's a "1:1"); everything else keeps its single existing participant.
# Steps that already have participants are left alone.

_LEADER_WORDS = ("manager", "leder", "leader")


def _participants_for(title: str, with_email: str) -> list[str]:
    current = (with_email or "").strip() or "leder"
    t = (title or "").lower()
    # "1:1" titles stay one-on-one even if they mention the buddy, e.g.
    # "Weekly 1:1 with manager (+ project status & buddy check-in)".
    if "buddy" in t and any(w in t for w in _LEADER_WORDS) and "1:1" not in t:
        out = ["leder", "buddy"]
        if current not in out:
            out.insert(0, current)
        return out
    return [current]


def forwards(apps, schema_editor):
    FlowStep = apps.get_model("onboarding", "FlowStep")
    changed = []
    for step in FlowStep.objects.filter(component_type="calendar_meeting"):
        config = dict(step.config or {})
        if config.get("participants"):
            continue
        config["participants"] = _participants_for(step.title, config.pop("with_email", ""))
        step.config = config
        changed.append(step)
    if changed:
        FlowStep.objects.bulk_update(changed, ["config"])


def backwards(apps, schema_editor):
    FlowStep = apps.get_model("onboarding", "FlowStep")
    changed = []
    for step in FlowStep.objects.filter(component_type="calendar_meeting"):
        config = dict(step.config or {})
        participants = config.pop("participants", None)
        if participants is None:
            continue
        config["with_email"] = participants[0] if participants else "leder"
        step.config = config
        changed.append(step)
    if changed:
        FlowStep.objects.bulk_update(changed, ["config"])


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0007_calendar_meeting_day_unit"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
