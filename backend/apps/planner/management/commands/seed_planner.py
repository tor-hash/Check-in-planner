from django.core.management.base import BaseCommand

from apps.planner.models import Person
from apps.planner.services.state import persist_state


def baseline_state():
    return {
        "people": [
            {
                "id": "jvo",
                "name": "Jonas Vo",
                "email": "jvo@blackcapitaltechnology.com",
                "org": "BCT",
            },
        ],
        "mgrs": ["jvo", "tor", "mr", "skj"],
        "teams": {"team-1": [], "team-2": [], "team-3": [], "pool": []},
        "startDate": "2026-01-05",
        "customDates": {},
        "workHours": {"start": "09:00", "end": "17:00", "excludeLunch": True, "weekdaysOnly": True},
        "viewedMgrFilter": "all",
        "weekOffset": 0,
        "projects": [],
        "journal": {},
        "fnTags": [
            {"label": "ENG", "displayName": "Engineering", "color": "#6ea8fe"},
            {"label": "BD", "displayName": "Business Development", "color": "#f5a97f"},
            {"label": "MKT", "displayName": "Marketing", "color": "#a6da95"},
            {"label": "MGMT", "displayName": "Management", "color": "#c6a0f6"},
        ],
    }


class Command(BaseCommand):
    help = "Seed planner baseline data into Django DB."

    def handle(self, *args, **options):
        if Person.objects.exists():
            self.stdout.write(self.style.WARNING("Planner data already exists. Skipping seed."))
            return
        persist_state(baseline_state(), user=None)
        self.stdout.write(self.style.SUCCESS("Seeded planner baseline data."))
