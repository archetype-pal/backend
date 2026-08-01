from django.db import migrations

# 0002 first seeded the About page as "about"; the site's canonical URL is
# /about/about-models-of-authority, which 0002 now writes. Rename the row on
# any DB that ran the earlier version so every environment converges.
LEGACY_ABOUT_SLUG = "about"
ABOUT_SLUG = "about-models-of-authority"

# The footer's Quick Links column as it stood before this table existed.
# Search Charters is a static route, not a Page, so it has no row to flag.
QUICK_LINK_SLUGS = [ABOUT_SLUG, "accessibility"]


def rename_legacy_about_slug(apps, schema_editor):
    Page = apps.get_model("pages", "Page")
    if Page.objects.filter(slug=ABOUT_SLUG).exists():
        return
    Page.objects.filter(slug=LEGACY_ABOUT_SLUG).update(slug=ABOUT_SLUG)


def set_quick_links(apps, schema_editor):
    Page = apps.get_model("pages", "Page")
    Page.objects.filter(slug__in=QUICK_LINK_SLUGS).update(include_in_quick_link=True)


def unset_quick_links(apps, schema_editor):
    Page = apps.get_model("pages", "Page")
    Page.objects.filter(slug__in=QUICK_LINK_SLUGS).update(include_in_quick_link=False)


class Migration(migrations.Migration):

    dependencies = [
        ("pages", "0003_page_include_in_quick_link"),
    ]

    operations = [
        # Forward-only: reversing the rename would leave 0002's unseed unable to
        # find the row it created.
        migrations.RunPython(rename_legacy_about_slug, migrations.RunPython.noop),
        migrations.RunPython(set_quick_links, unset_quick_links),
    ]
