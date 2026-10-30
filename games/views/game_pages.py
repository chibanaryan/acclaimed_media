"""A game's detail page and its played / want-to-play toggle."""

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView

from core.models import User
from core.services import seo
from games import config, constants, models
from games.cache import invalidate_played_games_cache, invalidate_want_to_play_cache


class GameDetailView(DetailView):
    model = models.Game
    template_name = "games/game_detail.html"
    context_object_name = "game"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        # with_relations() joins four levels of each developer's parents, so
        # `display_root_developer` reads them rather than querying a level at
        # a time, as the bare "developers__parent" prefetch here did. Lists
        # with publisher, sorted by year (desc), publication, list name.
        return models.Game.objects.with_relations().prefetch_related(
            Prefetch(
                "lists",
                queryset=models.ListMembership.objects.select_related(
                    "list__publisher",
                ).order_by(
                    "-list__year",  # Year (descending)
                    "list__publisher__name",  # Publication name (alphabetical)
                    "list__name",  # List name (alphabetical)
                    "rank",  # Rank within list
                ),
            ),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        game = context["game"]

        # Build grouped lists from prefetched data (preserves prefetch ordering:
        # publication importance desc, year desc, name, rank)
        from collections import defaultdict

        grouped = defaultdict(list)
        for membership in game.lists.all():
            list_type = membership.list.type
            label = constants.get_list_type_label(list_type)
            grouped[label].append(
                {
                    "id": membership.list.id,
                    "name": membership.list.name,
                    "publication": (
                        membership.list.publisher.name
                        if membership.list.publisher
                        else ""
                    ),
                    "publisher": membership.list.publisher,
                    "type": list_type,
                    "type_name": label,
                    "url": membership.list.url,
                    "year": membership.list.year,
                    "rank": membership.rank,
                }
            )

        # Order groups by type importance (All-time, Decade, Misc, EOY)
        type_order = ["All time", "Decade", "Miscellaneous", "End of year"]
        sorted_grouped_lists = [(k, grouped[k]) for k in type_order if k in grouped]

        context["grouped_lists"] = sorted_grouped_lists

        # Check if current user has marked this game as played or want-to-play
        if self.request.user.is_authenticated and game.igdb_id:
            context["is_played"] = models.PlayedGame.objects.filter(
                user=self.request.user, igdb_id=game.igdb_id
            ).exists()
            context["is_want_to_play"] = models.WantToPlayGame.objects.filter(
                user=self.request.user, igdb_id=game.igdb_id
            ).exists()

        # Get series with 2+ games (single-game series aren't useful)
        # Must query Series separately for accurate game counts
        series_ids = list(game.series.values_list("id", flat=True))
        context["series_list"] = (
            models.Series.objects.filter(id__in=series_ids)
            .annotate(games_count=Count("games"))
            .filter(games_count__gte=2)
            .order_by("name")
        )

        # Total game count for rank context (e.g., "#47 of 3,240")
        # Cached since it rarely changes
        total_game_count = cache.get("total_game_count")
        if total_game_count is None:
            total_game_count = models.Game.objects.count()
            cache.set(
                "total_game_count", total_game_count, config.CACHE_TIMEOUT_24_HOURS
            )
        context["total_game_count"] = total_game_count

        # Decade and year counts for rank context - cached by decade/year
        if game.decade:
            cache_key = f"{config.CACHE_VERSION}:decade_count:{game.decade}"
            decade_count = cache.get(cache_key)
            if decade_count is None:
                decade_count = models.Game.objects.filter(
                    year_of_release__gte=game.decade,
                    year_of_release__lte=game.decade + 9,
                ).count()
                cache.set(cache_key, decade_count, config.CACHE_TIMEOUT_24_HOURS)
            context["decade_game_count"] = decade_count

        if game.year_of_release:
            cache_key = f"{config.CACHE_VERSION}:year_count:{game.year_of_release}"
            year_count = cache.get(cache_key)
            if year_count is None:
                year_count = models.Game.objects.filter(
                    year_of_release=game.year_of_release
                ).count()
                cache.set(cache_key, year_count, config.CACHE_TIMEOUT_24_HOURS)
            context["year_game_count"] = year_count

        context["structured_data_json"] = _game_json_ld(game)
        return context


def _game_json_ld(game):
    """The VideoGame JSON-LD for a game's detail page.

    No ``aggregateRating``: the template used to emit one from
    ``game.score``, which does not exist, so every page published an empty
    rating, and a count of list appearances is not a rating either.
    """
    payload = {
        "@context": "https://schema.org",
        "@type": "VideoGame",
        "name": game.name,
        "url": settings.CANONICAL_ORIGIN
        + reverse("game-detail", kwargs={"slug": game.slug}),
        "description": game.description
        or "One of the most critically acclaimed video games of all time.",
    }
    if game.year_of_release:
        payload["datePublished"] = str(game.year_of_release)
    if game.image_og:
        payload["image"] = game.image_og
    return seo.json_ld(payload)


def _invalidate_tracking_caches(user_id):
    cache.delete("user_played_games_distribution")
    invalidate_played_games_cache(user_id)
    invalidate_want_to_play_cache(user_id)


class TogglePlayedGameView(LoginRequiredMixin, View):
    """
    Set or cycle a game's tracking status.

    If `status` query param is provided (none, want, played), sets directly.
    Otherwise cycles: none → want → played → none.

    States are mutually exclusive - a game cannot be both
    "want to play" and "played" simultaneously.
    """

    def post(self, request, igdb_id):
        game = get_object_or_404(models.Game, igdb_id=igdb_id)
        key = {"user": request.user, "igdb_id": igdb_id}

        target = request.GET.get("status")
        if target not in ("none", "want", "played"):
            # Legacy cycle behavior: none → want → played → none
            if models.PlayedGame.objects.filter(**key).exists():
                target = "none"
            elif models.WantToPlayGame.objects.filter(**key).exists():
                target = "played"
            else:
                target = "want"

        # One transaction, and update_or_create on the unique_together, as
        # music's toggle does: the delete-then-create this replaced let a
        # double-click race into an IntegrityError, and a row orphaned by a
        # re-import is re-adopted here rather than duplicated.
        with transaction.atomic():
            # One user's toggles run one at a time. Otherwise a Played and a
            # Want sent together (a fast re-pick in the menu) each delete
            # the other table before the other's insert is visible, and both
            # rows survive.
            User.objects.select_for_update().filter(pk=request.user.pk).first()
            if target == "played":
                models.WantToPlayGame.objects.filter(**key).delete()
                models.PlayedGame.objects.update_or_create(
                    **key, defaults={"game": game}
                )
            elif target == "want":
                models.PlayedGame.objects.filter(**key).delete()
                models.WantToPlayGame.objects.update_or_create(
                    **key, defaults={"game": game}
                )
            else:
                models.PlayedGame.objects.filter(**key).delete()
                models.WantToPlayGame.objects.filter(**key).delete()
        new_is_played = target == "played"
        new_is_want_to_play = target == "want"

        # After the commit, not inside it: a rolled-back transaction must not
        # leave the cache reflecting a write that did not happen.
        user_id = request.user.id
        transaction.on_commit(lambda: _invalidate_tracking_caches(user_id))

        # Preserve button size (large on game detail page, default elsewhere)
        size = request.GET.get("size")

        response = render(
            request,
            "games/includes/_played_button.html",
            {
                "game": game,
                "is_played": new_is_played,
                "is_want_to_play": new_is_want_to_play,
                "size": size,
                "just_toggled": True,
            },
        )
        # Prevent URL push for this HTMX action
        response["HX-Push-Url"] = "false"
        return response
