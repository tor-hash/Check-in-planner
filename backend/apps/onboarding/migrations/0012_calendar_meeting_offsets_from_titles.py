import re

from django.db import migrations

# Safety net for 0006, which only recognised an exact list of step titles:
# any calendar_meeting step that still has no day_offset gets one parsed
# from the "Week N · <day> [HH:MM] — …" prefix the flow's titles use, e.g.
#
#   "Week 1 · Mon 09:00 — Welcome …"        -> working day 0, 09:00
#   "Week 1 · Fri 10:00 — Wrap-up …"        -> working day 4, 10:00
#   "Week 3 · Tue–Thu — Independent work …" -> working day 11 (first day)
#   "Step 5 · Week 4 — Weekly 1:1 …"        -> working day 15 (Monday)
#
# Danish day names (man/tir/ons/tor/fre, "Uge N") work too. Steps that
# already have a day_offset, or whose title doesn't follow the pattern,
# are left alone.

_DAYS = {
    "mon": 0, "man": 0,
    "tue": 1, "tir": 1,
    "wed": 2, "ons": 2,
    "thu": 3, "tor": 3,
    "fri": 4, "fre": 4,
}
_WEEK_RE = re.compile(r"\b(?:week|uge|uke)\s*(\d+)", re.IGNORECASE)
_DAY_RE = re.compile(
    r"(?:week|uge|uke)\s*\d+\s*·\s*([A-Za-zæøå]{3})[A-Za-zæøå]*\.?(?:\s*[–-]\s*[A-Za-zæøå]+)?"
    r"(?:\s+(\d{1,2})[:.](\d{2}))?",
    re.IGNORECASE,
)


def schedule_from_title(title):
    """Return (day_offset, time_of_day or None) or None if not parseable."""
    prefix = (title or "").split(" — ", 1)[0]
    week = _WEEK_RE.search(prefix)
    if not week:
        return None
    offset = (int(week.group(1)) - 1) * 5
    time_of_day = None
    day = _DAY_RE.search(prefix)
    if day and day.group(1).lower() in _DAYS:
        offset += _DAYS[day.group(1).lower()]
        if day.group(2):
            h, m = int(day.group(2)), int(day.group(3))
            if h < 24 and m < 60:
                time_of_day = f"{h:02d}:{m:02d}"
    return max(offset, 0), time_of_day


def forwards(apps, schema_editor):
    FlowStep = apps.get_model("onboarding", "FlowStep")
    changed = []
    for step in FlowStep.objects.filter(component_type="calendar_meeting"):
        config = dict(step.config or {})
        if config.get("day_offset") is not None:
            continue
        parsed = schedule_from_title(step.title)
        if parsed is None:
            continue
        config["day_offset"], time_of_day = parsed
        config["day_unit"] = "business"
        if time_of_day and not config.get("time_of_day"):
            config["time_of_day"] = time_of_day
        step.config = config
        changed.append(step)
    if changed:
        FlowStep.objects.bulk_update(changed, ["config"])


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0011_onboardingsettings_system_email"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
