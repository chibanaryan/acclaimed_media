"""
Signals for the games app.
"""

import logging

from django.db import transaction
from django.db.models.signals import (
    m2m_changed,
    post_delete,
    post_save,
    pre_delete,
    pre_save,
)
from django.dispatch import receiver

from core.services.background import start_background_thread
from games.models import (
    Developer,
    Game,
    List,
    PlayedGame,
    Post,
    Publication,
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
    Email subscribers about a Post, on a background thread, once it commits.

    The emails used to go out inside the admin's save request, one SMTP
    send per subscriber, so a large enough list would outrun Heroku's 30 s
    router timeout. The post is claimed first - `notification_sent` flipped
    by a conditional update that only one save can win - so a second save
    while the emails are still going out cannot send them again. The thread
    starts on commit, so it reads the saved post, and a save that rolls
    back sends nothing.
    """
    if not getattr(instance, "_should_send_notification", False):
        return
    instance._should_send_notification = False

    claimed = Post.objects.filter(pk=instance.pk, notification_sent=False).update(
        notification_sent=True
    )
    if not claimed:
        return
    # So a later save of this same object cannot write False back
    instance.notification_sent = True

    post_pk = instance.pk
    logger.info(f"Queued notification emails for post '{instance.title or post_pk}'")
    # Not a daemon: a deploy's graceful shutdown waits for the send rather
    # than cutting it off. A hard kill can still stop it part-way; the post
    # stays marked sent (resending would mail those already reached), and
    # the start and finish lines in the log show whether it completed.
    transaction.on_commit(
        lambda: start_background_thread(
            lambda: _notify_subscribers(post_pk), daemon=False
        )
    )


def _notify_subscribers(post_pk):
    # Import here to avoid circular import
    from games import utils

    post = Post.objects.get(pk=post_pk)
    logger.info(f"Sending notification emails for post '{post.title or post_pk}'")
    sent_count = utils.notify_subscribers_of_new_post(post)
    logger.info(
        f"Sent {sent_count} notification emails for post '{post.title or post_pk}'"
    )


# =============================================================================
# Developer Hierarchy Cache Invalidation
# =============================================================================


@receiver(pre_save, sender=Developer)
def remember_the_root_a_developer_leaves(sender, instance, **kwargs):
    """Note what a save changes, for `invalidate_developer_cache_on_change`.

    The old root of a studio moving parent, whose page still lists it. And
    whether anything changed at all: the IGDB refresh saves every developer on
    every game, and a drop for each would keep the whole family uncached for as
    long as it ran.
    """
    instance._root_left_id = None
    instance._save_changes_nothing = False
    if instance.pk is None or kwargs.get("raw"):
        return
    fields = [
        field.attname
        for field in Developer._meta.concrete_fields
        if not getattr(field, "auto_now", False)
    ]
    previous = Developer.objects.filter(pk=instance.pk).values(*fields).first()
    if previous is None:
        return
    instance._save_changes_nothing = all(
        previous[name] == getattr(instance, name) for name in fields
    )
    old_parent_id = previous["parent_id"]
    if old_parent_id and old_parent_id != instance.parent_id:
        old_parent = Developer.objects.filter(pk=old_parent_id).first()
        if old_parent:
            instance._root_left_id = old_parent.root_developer.id


@receiver([post_save, post_delete], sender=Developer)
def invalidate_developer_cache_on_change(sender, instance, **kwargs):
    """Invalidate developer hierarchy cache when Developer changes."""
    from games.cache import invalidate_developer_detail
    from games.services.developer_service import invalidate_developer_cache

    if kwargs.get("created") is False and instance._save_changes_nothing:
        return

    invalidate_developer_cache()

    # Also invalidate detail page caches for this developer and its root
    invalidate_developer_detail(instance.id)
    root_left_id = getattr(instance, "_root_left_id", None)
    if root_left_id:
        invalidate_developer_detail(root_left_id)
    # Cached on the instance, and it may have just changed parent.
    instance.__dict__.pop("root_creator", None)
    instance.__dict__.pop("root_developer", None)
    if instance.parent_id:
        # Invalidate root developer's detail cache too
        # Use try-except because parent may already be deleted during bulk deletion
        try:
            root = instance.root_developer
            invalidate_developer_detail(root.id)
        except Developer.DoesNotExist:
            pass

    logger.debug("Developer hierarchy cache invalidated (Developer changed)")


@receiver(m2m_changed, sender=Game.developers.through)
def invalidate_developer_cache_on_game_change(sender, instance, pk_set, **kwargs):
    """Invalidate developer hierarchy cache when Game.developers M2M changes."""
    from games.cache import invalidate_developer_detail
    from games.services.developer_service import invalidate_developer_cache

    invalidate_developer_cache()

    # Invalidate detail page caches for affected developers
    if pk_set:
        for dev_id in pk_set:
            invalidate_developer_detail(dev_id)
            # Also invalidate root developer's cache
            try:
                dev = Developer.objects.get(id=dev_id)
                if dev.parent_id:
                    root = dev.root_developer
                    invalidate_developer_detail(root.id)
            except Developer.DoesNotExist:
                pass

    logger.debug("Developer hierarchy cache invalidated (Game.developers changed)")


# =============================================================================
# Homepage Hero Stats Cache Invalidation
# =============================================================================


@receiver([post_save, post_delete], sender=Game)
@receiver([post_save, post_delete], sender=List)
@receiver([post_save, post_delete], sender=Publication)
def invalidate_hero_stats_on_count_change(sender, instance, **kwargs):
    """Invalidate homepage hero stats cache when a count it holds changes.

    Not on an ordinary save, which changes no count: the weekly refresh saves
    every game, and the entry would never survive it. `post_delete` sends no
    ``created``.
    """
    from games.cache import invalidate_hero_stats

    if kwargs.get("created", True):
        invalidate_hero_stats()
        logger.debug("Homepage hero stats cache invalidated (count changed)")


@receiver(pre_delete, sender=Game)
def invalidate_developer_pages_on_game_delete(sender, instance, **kwargs):
    """A cascade removes its through rows with no `m2m_changed`, so the
    developer pages would go on counting a game that is gone. Before the delete,
    while the links can still be read; a whole import's deletes make one drop."""
    from games.cache import invalidate_developer_detail
    from games.services.developer_service import invalidate_developer_cache

    invalidate_developer_cache()
    for developer in instance.developers.all():
        invalidate_developer_detail(developer.id)
        if developer.parent_id:
            invalidate_developer_detail(developer.root_developer.id)


@receiver(post_delete, sender=Game)
def invalidate_played_counts_on_game_delete(sender, instance, **kwargs):
    """A deleted game orphans its PlayedGame rows, and SET_NULL sends no signal."""
    from games.cache import invalidate_played_counts

    invalidate_played_counts()


# =============================================================================
# User Tracking Cache Invalidation (PlayedGame / WantToPlayGame)
# =============================================================================


@receiver([post_save, post_delete], sender=PlayedGame)
def invalidate_played_game_cache(sender, instance, **kwargs):
    """Invalidate played games cache when PlayedGame changes."""
    from games.cache import invalidate_played_counts, invalidate_played_games_cache

    invalidate_played_games_cache(instance.user_id)
    invalidate_played_counts()
    logger.debug(f"Played games cache invalidated (user {instance.user_id})")


@receiver([post_save, post_delete], sender=WantToPlayGame)
def invalidate_want_to_play_game_cache(sender, instance, **kwargs):
    """Invalidate want-to-play games cache when WantToPlayGame changes."""
    from games.cache import invalidate_want_to_play_cache

    invalidate_want_to_play_cache(instance.user_id)
    logger.debug(f"Want-to-play games cache invalidated (user {instance.user_id})")
