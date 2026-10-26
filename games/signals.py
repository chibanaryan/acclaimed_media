"""
Signals for the games app.
"""

import logging
import sys

from django.apps import apps as global_apps
from django.db import DEFAULT_DB_ALIAS, router
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver

from games import open_ended
from games.models import (
    Developer,
    Game,
    PlayedGame,
    Post,
    WantToPlayGame,
)

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Post)
def check_should_notify(sender, instance, **kwargs):
    """
    Check if we should send email notifications for this Post.

    Notifications are sent when:
    - Post is active (published)
    - AND send_notification is checked
    - AND notification hasn't been sent yet (notification_sent=False)

    This ensures each post only triggers notifications once, even if edited later.
    """
    # Check if post should trigger notification
    if (
        instance.active
        and instance.send_notification
        and not instance.notification_sent
    ):
        # Mark that we should send notification after save
        instance._should_send_notification = True
        post_id = instance.title or instance.pk
        logger.info(f"Post '{post_id}' will trigger notification after save.")
    else:
        instance._should_send_notification = False


@receiver(post_save, sender=Post)
def send_notification_after_save(sender, instance, created, **kwargs):
    """
    Send email notifications after Post is saved (if flagged for notification).

    This runs after the post is saved to the database, ensuring the post ID
    and all fields are properly set before sending emails.
    """
    # Check if we should send notification (flag set in pre_save)
    if getattr(instance, "_should_send_notification", False):
        logger.info(
            f"Sending notifications for post '{instance.title or instance.pk}'..."
        )

        # Import here to avoid circular import
        from games import utils

        # Notify all subscribers
        sent_count = utils.notify_subscribers_of_new_post(instance)
        post_id = instance.title or instance.pk
        logger.info(f"Sent {sent_count} notification emails for post '{post_id}'")

        # Mark notification as sent (use update to avoid triggering another save)
        Post.objects.filter(pk=instance.pk).update(notification_sent=True)

        # Clean up the flag
        instance._should_send_notification = False


# =============================================================================
# Developer Hierarchy Cache Invalidation
# =============================================================================


@receiver([post_save, post_delete], sender=Developer)
def invalidate_developer_cache_on_change(sender, instance, **kwargs):
    """Invalidate developer hierarchy cache when Developer changes."""
    from django.core.cache import cache

    from games import config
    from games.services.developer_service import invalidate_developer_cache

    invalidate_developer_cache()

    # Also invalidate detail page caches for this developer and its root
    cache.delete(f"{config.CACHE_VERSION}:developer_detail:{instance.id}")
    if instance.parent_id:
        # Invalidate root developer's detail cache too
        # Use try-except because parent may already be deleted during bulk deletion
        try:
            root = instance.root_developer
            cache.delete(f"{config.CACHE_VERSION}:developer_detail:{root.id}")
        except Developer.DoesNotExist:
            pass

    logger.debug("Developer hierarchy cache invalidated (Developer changed)")


@receiver(m2m_changed, sender=Game.developers.through)
def invalidate_developer_cache_on_game_change(sender, instance, pk_set, **kwargs):
    """Invalidate developer hierarchy cache when Game.developers M2M changes."""
    from django.core.cache import cache

    from games import config
    from games.services.developer_service import invalidate_developer_cache

    invalidate_developer_cache()

    # Invalidate detail page caches for affected developers
    if pk_set:
        for dev_id in pk_set:
            cache.delete(f"{config.CACHE_VERSION}:developer_detail:{dev_id}")
            # Also invalidate root developer's cache
            try:
                dev = Developer.objects.get(id=dev_id)
                if dev.parent_id:
                    root = dev.root_developer
                    cache.delete(f"{config.CACHE_VERSION}:developer_detail:{root.id}")
            except Developer.DoesNotExist:
                pass

    logger.debug("Developer hierarchy cache invalidated (Game.developers changed)")


# =============================================================================
# Homepage Hero Stats Cache Invalidation
# =============================================================================


@receiver([post_save, post_delete], sender=Game)
def invalidate_hero_stats_on_game_change(sender, instance, **kwargs):
    """Invalidate homepage hero stats cache when Game count changes."""
    from django.core.cache import cache

    cache.delete("homepage_hero_stats")
    logger.debug("Homepage hero stats cache invalidated (Game changed)")


# =============================================================================
# User Tracking Cache Invalidation (PlayedGame / WantToPlayGame)
# =============================================================================


@receiver([post_save, post_delete], sender=PlayedGame)
def invalidate_played_game_cache(sender, instance, **kwargs):
    """Invalidate played games cache when PlayedGame changes."""
    from games.cache import invalidate_played_games_cache

    invalidate_played_games_cache(instance.user_id)
    logger.debug(f"Played games cache invalidated (user {instance.user_id})")


@receiver([post_save, post_delete], sender=WantToPlayGame)
def invalidate_want_to_play_game_cache(sender, instance, **kwargs):
    """Invalidate want-to-play games cache when WantToPlayGame changes."""
    from games.cache import invalidate_want_to_play_cache

    invalidate_want_to_play_cache(instance.user_id)
    logger.debug(f"Want-to-play games cache invalidated (user {instance.user_id})")


def rederive_open_ended(
    verbosity=2, using=DEFAULT_DB_ALIAS, apps=global_apps, **kwargs
):
    """
    After every ``migrate`` - and so on every deploy, whose release phase runs
    it - bring ``HLTBGameData.is_open_ended`` in line with the editorial calls
    in ``games/open_ended.py``, so editing a list needs no migration. Writes
    only the rows whose flag changes, and says so when any did. Defaults match
    Django's own receivers, since ``flush`` sends the signal without ``apps``
    or ``stdout``. Connected in ``GamesConfig.ready``.
    """
    try:
        HLTBGameData = apps.get_model("games", "HLTBGameData")
    except LookupError:
        return  # migrated back past the model
    if "is_open_ended" not in {f.name for f in HLTBGameData._meta.get_fields()}:
        return  # migrated back past 0116
    if not router.allow_migrate_model(using, HLTBGameData):
        return  # a database that does not hold the games tables
    changed = open_ended.derive_all(HLTBGameData, using=using)
    if changed and verbosity:
        kwargs.get("stdout", sys.stdout).write(
            f"Re-derived is_open_ended on {changed} HLTB rows\n"
        )
