"""Move the Sites framework domain to acclaimedmedia.org.

The sitemap builds its absolute URLs from Site.domain, so it has to follow
the canonical origin (settings.CANONICAL_ORIGIN) from www.acclaimedvideogames.com
(or the bare apex, which 0109 moved from) to the new domain's root.
"""

from django.db import migrations

CANONICAL_DOMAIN = "acclaimedmedia.org"
OLD_DOMAINS = ("www.acclaimedvideogames.com", "acclaimedvideogames.com")


def _rename(Site, old_domains, new_domain):
    # Site.domain is unique, so rename one row at most, and none if a row
    # already carries the new domain
    if Site.objects.filter(domain=new_domain).exists():
        return
    site = Site.objects.filter(domain__in=old_domains).order_by("pk").first()
    if site is not None:
        site.domain = new_domain
        site.save(update_fields=["domain"])


def forwards(apps, schema_editor):
    _rename(apps.get_model("sites", "Site"), OLD_DOMAINS, CANONICAL_DOMAIN)


def backwards(apps, schema_editor):
    _rename(apps.get_model("sites", "Site"), (CANONICAL_DOMAIN,), OLD_DOMAINS[0])


class Migration(migrations.Migration):

    dependencies = [
        ("games", "0121_developer_series_name_normalized"),
        ("sites", "0002_alter_domain_unique"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
