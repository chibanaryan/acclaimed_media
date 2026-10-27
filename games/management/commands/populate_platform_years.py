"""
Management command to populate platform year_start and year_end fields.

Usage:
    python manage.py populate_platform_years
"""

from django.core.management.base import BaseCommand
from games.models import Platform
from games.platform_years import PLATFORM_YEAR_RANGES


class Command(BaseCommand):
    help = "Populate year_start and year_end for all platforms"

    def handle(self, *args, **options):
        updated_count = 0
        missing_count = 0

        self.stdout.write("Populating platform year ranges...")

        for platform in Platform.objects.all():
            if platform.code in PLATFORM_YEAR_RANGES:
                year_start, year_end = PLATFORM_YEAR_RANGES[platform.code]
                platform.year_start = year_start
                platform.year_end = year_end
                platform.save(update_fields=["year_start", "year_end"])
                updated_count += 1
                end_str = year_end if year_end else "present"
                self.stdout.write(
                    f"  ✓ {platform.code} ({platform.name}): {year_start}-{end_str}"
                )
            else:
                missing_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  ⚠ {platform.code} ({platform.name}): No year data available"
                    )
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ Updated {updated_count} platforms, "
                f"{missing_count} missing year data"
            )
        )
