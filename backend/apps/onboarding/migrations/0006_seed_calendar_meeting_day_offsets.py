from django.db import migrations

# Best-effort backfill: your existing onboarding flow's calendar_meeting
# steps encode their intended day/time only in human-readable titles like
# "Week 1 · Mon 09:00 — Welcome with manager & buddy". This migration maps
# those known titles onto the new config.day_offset (business days after
# the employee's start date, start date itself = 0) / config.time_of_day
# fields that calendar_booking.py now actually schedules from — see
# components.CalendarMeetingComponent and calendar_booking._business_day_offset.
#
# Matches by the title text after the " — " separator, scoped to component_type="calendar_meeting",
# and only fills in a step that doesn't already have day_offset set (so
# re-running this, or running it after you've hand-edited a step in the
# Flow editor, never clobbers a deliberate choice).
#
# Deliberately NOT covered here (left on the old "first available slot"
# behavior — set day_offset/time_of_day by hand in the Flow editor if you
# want these anchored too):
#   - The three "Milestone · N days" steps (30/60/90-day conversations) —
#     those are a calendar-day concept ("the 30th day since starting"),
#     not a business-day-in-a-templated-week concept, and this migration
#     only implements the latter.
#   - Any step whose title doesn't exactly match one below (e.g. if you've
#     since renamed one).
#
# Week 2/3's single-weekday steps and the Week1 Tue-Thu blocks get a
# day_offset (so the week itself still shifts correctly) but no
# time_of_day, since the original titles didn't specify one — booking
# falls back to "first available slot" on the correct day, same as today.

TITLE_SCHEDULE = {
    # Week 1
    "Welcome with manager & buddy": (0, "09:00"),
    "Equipment & merch handout": (0, "10:00"),
    "Intro to BCT method & delivery model": (0, "11:00"),
    "Lunch with the team": (0, "12:00"),
    "Google Workspace, Slack, Notion & security": (0, "13:00"),
    "Self time: setup & documentation": (0, "15:00"),
    "Team photo + review of ongoing projects": (1, "09:00"),
    "Role & expectations talk with manager": (1, "10:30"),
    "Role-related professional deep-dive": (1, "13:00"),
    "Sync with buddy": (1, "15:00"),
    "Shadowing in an active project": (2, "09:00"),
    "Workshop: how to create value in practice": (2, "13:00"),
    "Review chosen project for week 2": (2, "15:00"),
    "Meeting with project lead": (3, "09:00"),
    "Define the first deliverable": (3, "10:00"),
    "Preparation for project start": (3, "13:00"),
    "Wrap-up with buddy": (4, "09:00"),
    "Wrap-up with manager": (4, "10:00"),
    "Define 30-day goals with manager": (4, "11:00"),
    # Week 2 (business day 5 = Mon of week 2)
    "Project kickoff meeting": (5, None),
    "Work on first deliverable (2 buddy syncs)": (6, None),  # anchored to Tue
    "Short status meeting with manager": (9, None),  # Fri
    # Week 3 (business day 10 = Mon of week 3)
    "Status meeting with project lead": (10, None),
    "Independent work on deliverables": (11, None),  # anchored to Tue-Thu block's Tue
    "30-min reflection with buddy": (12, None),  # Wed
    "Meeting with manager (progress & goals)": (14, None),  # Fri
    # Week 4 (business day 15 = Mon of week 4)
    "Weekly 1:1 with manager (+ project status & buddy check-in)": (15, None),
}


def seed_day_offsets(apps, schema_editor):
    FlowStep = apps.get_model("onboarding", "FlowStep")
    steps = FlowStep.objects.filter(component_type="calendar_meeting")
    changed = []
    for step in steps:
        # Titles in the flow carry a "Week 1 · Mon 09:00 — " prefix; match
        # on the part after the dash (or the whole title if there's none).
        key = step.title.split(" — ", 1)[-1].strip()
        if key not in TITLE_SCHEDULE:
            continue
        config = step.config or {}
        if config.get("day_offset") is not None:
            continue  # already set (by hand, or a previous run) — leave it
        day_offset, time_of_day = TITLE_SCHEDULE[key]
        config["day_offset"] = day_offset
        if time_of_day:
            config["time_of_day"] = time_of_day
        step.config = config
        changed.append(step)
    if changed:
        FlowStep.objects.bulk_update(changed, ["config"])


def noop_reverse(apps, schema_editor):
    # Not worth reversing — day_offset/time_of_day are additive fields;
    # removing them would just put steps back on the old scheduling
    # behavior, which isn't a meaningful "undo" of anything destructive.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0005_fix_manager_placeholder_organizer"),
    ]

    operations = [
        migrations.RunPython(seed_day_offsets, noop_reverse),
    ]
