from django.core.management.base import BaseCommand

from apps.planner.models import Person
from apps.planner.seed_baseline import baseline_state
from apps.planner.services.state import persist_state


class Command(BaseCommand):
    help = "Seed planner baseline data into Django DB."

    def handle(self, *args, **options):
        if Person.objects.exists():
            self.stdout.write(self.style.WARNING("Planner data already exists. Skipping seed."))
            return
        persist_state(baseline_state(), user=None)
        self.stdout.write(self.style.SUCCESS("Seeded planner baseline data."))
