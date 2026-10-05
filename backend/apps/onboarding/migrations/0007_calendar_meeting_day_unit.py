import re

from django.db import migrations

# Follow-up to 0006, for the new config.day_unit field (see
# components.CalendarMeetingComponent):
#
# * Drops the unused "suggested_window" key from every calendar_meeting step
#   (it was never read by the booking code and is removed from the editor).
# * Steps that already have a day_offset get day_unit="business" explicitly,
#   so the week-by-week template keeps counting working days.
# * "Milestone · N days — …" calendar meetings without a day_offset get
#   day_offset=N, day_unit="calendar" — i.e. N plain calendar days after the
#   start date, rolled forward past weekends/holidays.
#
# Never overwrites a day_offset/day_unit that's already set.

MILESTONE_RE = re.compile(r"^\s*Milestone\s*·\s*(\d+)\s*days?\b", re.IGNORECASE)


def forwards(apps, schema_editor):
    FlowStep = apps.get_model("onboarding", "FlowStep")
    changed = []
    for step in FlowStep.objects.filter(component_type="calendar_meeting"):
        config = dict(step.config or {})
        before = dict(config)
        config.pop("suggested_window", None)
        if config.get("day_offset") is not None:
            config.setdefault("day_unit", "business")
        else:
            m = MILESTONE_RE.match(step.title or "")
            if m:
                config["day_offset"] = int(m.group(1))
                config["day_unit"] = "calendar"
        if config != before:
            step.config = config
            changed.append(step)
    if changed:
        FlowStep.objects.bulk_update(changed, ["config"])


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0006_seed_calendar_meeting_day_offsets"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
