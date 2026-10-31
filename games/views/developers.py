"""The developers list, a developer's page, and the old alias redirect."""

import math

from django.db.models import Count, Max, Prefetch, prefetch_related_objects
from django.shortcuts import redirect, get_object_or_404
from django.views import View
from django.views.generic import ListView, DetailView

from core.mixins import HTMXPartialMixin, RobustPaginationMixin
from core.services.query_params import parse_int
from core.cache_helpers import current_generation, set_if_current
from games import config, models
from games.cache import GENERATION_DEVELOPERS, developer_detail_cache_key
from games.services import playtime


class DeveloperListView(RobustPaginationMixin, HTMXPartialMixin, ListView):
    """
    List view for developers with game counts and hierarchy support.

    Uses the unified Developer model with self-referential parent FK for hierarchy.
    Leverages cached hierarchy data for performance optimization.
    """

    model = models.Developer
    template_name = "developers/developer_list.html"
    context_object_name = "developers"
    paginate_by = 100
    paginate_orphans = 0
    htmx_partial_template = "developers/includes/_developer_list_content.html"

    def get_template_names(self):
        # Append mode for Load More - returns just rows
        if self.request.GET.get("append") == "true":
            return ["developers/includes/_developer_list_append.html"]
        return super().get_template_names()

    SORTS = ("games", "studios", "rank", "name")

    def get_paginate_by(self, queryset):
        # Pagination is manual, in get_context_data, for every sort: it has
        # to come after developers with no games are dropped, or a page is
        # short of them and the total counts them. The name sort used
        # Django's paginator and so listed every one of them.
        return None

    def _sort(self):
        sort = self.request.GET.get("sort", "games")
        return sort if sort in self.SORTS else "games"

    def get_queryset(self):
        qs = (
            models.Developer.objects.annotate(
                games_count=Count("developed_games"),
            )
            .select_related("parent")
            .prefetch_related("subsidiaries")
            .distinct()
        )

        # Search filter
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(name__icontains=q)

        # Sorting is done in get_context_data, from cached hierarchy data
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sort = self._sort()
        direction = self.request.GET.get("dir", "asc")
        context["sort"] = sort
        context["sort_options"] = config.DEVELOPER_SORT_OPTIONS

        # Get cached hierarchy data (precomputed counts, game IDs, etc.)
        from games.services.developer_service import get_developer_hierarchy

        hierarchy = get_developer_hierarchy()

        # Get developers list
        developers = list(context.get("developers", []))

        # Attach precomputed counts from cache (no recursive queries!)
        for dev in developers:
            dev.recursive_games_count = hierarchy["recursive_game_counts"].get(
                dev.id, 0
            )
            dev.recursive_studios_count = hierarchy["recursive_subsidiary_counts"].get(
                dev.id, 0
            )

        # Filter out developers with no games (direct or through subsidiaries)
        developers = [d for d in developers if d.recursive_games_count > 0]

        # Pre-attach root developers to avoid template N+1 queries
        root_ids = set(
            hierarchy["root_developer_id"].get(dev.id, dev.id) for dev in developers
        )
        root_devs = {d.id: d for d in models.Developer.objects.filter(id__in=root_ids)}
        for dev in developers:
            root_id = hierarchy["root_developer_id"].get(dev.id, dev.id)
            dev._prefetched_root = root_devs.get(root_id, dev)

        # For rank sorting, fetch top games using cached top_game_id
        if sort == "rank":
            top_game_ids = [
                hierarchy["top_game_id"].get(dev.id)
                for dev in developers
                if hierarchy["top_game_id"].get(dev.id) is not None
            ]
            if top_game_ids:
                top_games = {
                    g.id: g
                    for g in models.Game.objects.filter(id__in=top_game_ids)
                    .select_related("primary_igdb_game_data")
                    .only(
                        "id",
                        "name",
                        "slug",
                        "rank",
                        "year_of_release",
                        "primary_igdb_game_data",
                    )
                }
                for dev in developers:
                    top_game_id = hierarchy["top_game_id"].get(dev.id)
                    if top_game_id and top_game_id in top_games:
                        dev.top_game = top_games[top_game_id]

        # Sort by cached counts (with direction support)
        is_desc = direction == "desc"
        if sort == "name":
            developers.sort(key=lambda d: d.name.lower(), reverse=is_desc)
        elif sort == "games":
            developers.sort(
                key=lambda d: (
                    (
                        -d.recursive_games_count
                        if not is_desc
                        else d.recursive_games_count
                    ),
                    d.name.lower(),
                )
            )
        elif sort == "studios":
            developers.sort(
                key=lambda d: (
                    (
                        -d.recursive_studios_count
                        if not is_desc
                        else d.recursive_studios_count
                    ),
                    d.name.lower(),
                )
            )
        else:  # rank
            developers.sort(
                key=lambda d: (
                    getattr(d, "top_game", None) is None,  # No game = always last
                    (
                        (getattr(getattr(d, "top_game", None), "rank", 9999) or 9999)
                        if not is_desc
                        else -(
                            getattr(getattr(d, "top_game", None), "rank", 9999) or 9999
                        )
                    ),
                    d.name.lower(),
                )
            )

        # Manual pagination; past the end means the last page, as
        # RobustPaginationMixin answers
        per_page = self.paginate_by
        total_count = len(developers)
        last_page = max(1, math.ceil(total_count / per_page))
        page = min(max(1, parse_int(self.request.GET.get("page"), 1)), last_page)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page

        # Slice for current page
        context["developers"] = developers[start_idx:end_idx]

        # Build pagination context
        context["has_more"] = end_idx < total_count
        context["next_page"] = page + 1 if end_idx < total_count else None
        context["total_count"] = total_count
        context["loaded_count"] = min(end_idx, total_count)
        context["remaining_count"] = max(0, total_count - end_idx)

        # Fetch top game for each developer on the current page (if not already set)
        page_developers = context.get("developers", [])
        devs_needing_top_game = [
            dev for dev in page_developers if not hasattr(dev, "top_game")
        ]

        if devs_needing_top_game:
            top_game_ids = [
                hierarchy["top_game_id"].get(dev.id)
                for dev in devs_needing_top_game
                if hierarchy["top_game_id"].get(dev.id) is not None
            ]
            if top_game_ids:
                top_games = {
                    g.id: g
                    for g in models.Game.objects.filter(id__in=top_game_ids)
                    .select_related("primary_igdb_game_data")
                    .only(
                        "id",
                        "name",
                        "slug",
                        "rank",
                        "year_of_release",
                        "primary_igdb_game_data",
                    )
                }
                for dev in devs_needing_top_game:
                    top_game_id = hierarchy["top_game_id"].get(dev.id)
                    if top_game_id and top_game_id in top_games:
                        dev.top_game = top_games[top_game_id]

        return context


# Legacy alias for backward compatibility
StudioListView = DeveloperListView


class DeveloperDetailView(DetailView):
    """
    Detail view for a developer showing all games and subsidiary hierarchy.

    Uses the unified Developer model with self-referential parent FK.
    Caches expensive context computation for 24 hours.
    """

    CACHE_SCHEMA_VERSION = 2

    model = models.Developer
    template_name = "developers/developer_detail.html"
    context_object_name = "developer"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    # How many levels of subsidiaries the uncached build prefetches. Deeper
    # ones still work, a query per developer.
    HIERARCHY_PREFETCH_DEPTH = 3

    def _prefetch_hierarchy(self, developer):
        """Prefetch the subsidiary tree and each level's games for the
        uncached build, which needs only their ids and ranks: the games it
        renders are re-read with their relations by ``_fetch_games_by_ids``.

        Kept out of ``get_queryset`` so that a cache hit, which needs none
        of it, does not load every game the developer has.
        """
        light_games = models.Game.objects.only("id", "rank")
        lookups = [Prefetch("developed_games", queryset=light_games)]
        path = ""
        for _ in range(self.HIERARCHY_PREFETCH_DEPTH):
            path += "subsidiaries"
            lookups.append(
                Prefetch(path, queryset=models.Developer.objects.order_by("name"))
            )
            lookups.append(Prefetch(f"{path}__developed_games", queryset=light_games))
            path += "__"
        # One level further without games, so the walk finds the deepest
        # prefetched studios' (usually empty) subsidiaries without a query each.
        lookups.append(
            Prefetch(
                path + "subsidiaries",
                queryset=models.Developer.objects.order_by("name"),
            )
        )
        prefetch_related_objects([developer], *lookups)

    def _get_cached_context(self, developer):
        """Get cached context for this developer, or None if not cached."""
        from django.core.cache import cache

        cache_key = developer_detail_cache_key(developer.id)
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            cached_schema = cached.get("cache_schema_version")
            if cached_schema is not None and cached_schema != self.CACHE_SCHEMA_VERSION:
                cache.delete(cache_key)
                return None
            if cached_schema == self.CACHE_SCHEMA_VERSION:
                return cached
            # Drop legacy cached payloads that stored model objects.
            if "all_games" in cached and "subsidiaries_with_games" in cached:
                cache.delete(cache_key)
                return None
        return cached

    def _set_cached_context(self, developer, context_data):
        """Cache the expensive context data for this developer."""
        set_if_current(
            developer_detail_cache_key(developer.id),
            context_data,
            config.CACHE_TIMEOUT_24_HOURS,
            GENERATION_DEVELOPERS,
            self._cache_generation,
        )

    @staticmethod
    def _serialize_developer(developer):
        return {
            "id": developer.id,
            "name": developer.name,
            "igdb_url": developer.igdb_url,
            "slug": developer.slug,
        }

    def _serialize_subsidiaries(self, devs_data):
        serialized = []
        for dev_data in devs_data:
            serialized.append(
                {
                    "developer_id": dev_data["developer"].id,
                    "developer": self._serialize_developer(dev_data["developer"]),
                    "game_ids": [g.id for g in dev_data["games"]],
                    "games_count": dev_data["games_count"],
                    "sub_developers": self._serialize_subsidiaries(
                        dev_data["sub_developers"]
                    ),
                    "total_games_count": dev_data["total_games_count"],
                    "total_developers_count": dev_data["total_developers_count"],
                }
            )
        return serialized

    @staticmethod
    def _collect_developer_ids(serialized):
        developer_ids = set()
        stack = list(serialized or [])
        while stack:
            dev_data = stack.pop()
            if not isinstance(dev_data, dict):
                continue
            dev_id = dev_data.get("developer_id")
            if dev_id is None:
                dev = dev_data.get("developer")
                if isinstance(dev, dict):
                    dev_id = dev.get("id")
                else:
                    dev_id = getattr(dev, "id", None)
            if dev_id is not None:
                developer_ids.add(dev_id)
            stack.extend(dev_data.get("sub_developers", []) or [])
        return developer_ids

    def _hydrate_subsidiaries(self, serialized, games_by_id, developers_by_id):
        hydrated = []
        for dev_data in serialized:
            game_ids = dev_data.get("game_ids", [])
            games = [games_by_id[gid] for gid in game_ids if gid in games_by_id]
            dev_id = dev_data.get("developer_id")
            dev = dev_data.get("developer")
            if dev_id is None:
                if isinstance(dev, dict):
                    dev_id = dev.get("id")
                else:
                    dev_id = getattr(dev, "id", None)
            dev_obj = developers_by_id.get(dev_id) if dev_id is not None else None
            if dev_obj is None:
                dev_obj = dev
            sub_devs = self._hydrate_subsidiaries(
                dev_data.get("sub_developers", []), games_by_id, developers_by_id
            )
            hydrated.append(
                {
                    "developer": dev_obj,
                    "games": games,
                    "games_count": dev_data.get("games_count", len(games)),
                    "sub_developers": sub_devs,
                    "total_games_count": dev_data.get("total_games_count", len(games)),
                    "total_developers_count": dev_data.get(
                        "total_developers_count", len(sub_devs)
                    ),
                }
            )
        return hydrated

    @staticmethod
    def _fetch_games_by_ids(game_ids):
        from games.models import Game

        if not game_ids:
            return [], {}

        # with_relations() selects the IGDB row the thumbnails read and the
        # developer parent chain the credit line walks; without them a
        # 120-game developer page cost 338 queries on a cache hit.
        games = list(Game.objects.filter(id__in=game_ids).with_relations())
        games_by_id = {game.id: game for game in games}
        ordered_games = [games_by_id[gid] for gid in game_ids if gid in games_by_id]
        return ordered_games, games_by_id

    @classmethod
    def _swap_in_games(cls, devs_data, games_by_id):
        """Replace each level's games with the instances in ``games_by_id``.

        A game deleted between the two reads is dropped, as the cached path
        drops it, rather than raising.
        """
        for dev_data in devs_data:
            dev_data["games"] = [
                games_by_id[g.id] for g in dev_data["games"] if g.id in games_by_id
            ]
            cls._swap_in_games(dev_data["sub_developers"], games_by_id)

    def flatten_developers(
        self, devs_data, parent_id=None, level=0, continues_at_levels=None
    ):
        """Flatten recursive developer structure for checkbox tree.

        Tracks tree structure for proper tree line rendering:
        - is_last_child: whether item is last sibling (vertical line stops at 50%)
        - continues_at_levels: ancestor levels with more siblings (need vertical lines)
        """
        if continues_at_levels is None:
            continues_at_levels = []

        flat = []
        total = len(devs_data)
        for idx, dev_data in enumerate(devs_data):
            is_last = idx == total - 1
            child_ids = [s["developer"].id for s in dev_data["sub_developers"]]

            flat.append(
                {
                    "id": dev_data["developer"].id,
                    "name": dev_data["developer"].name,
                    "igdb_url": dev_data["developer"].igdb_url,
                    "game_ids": [g.id for g in dev_data["games"]],
                    "total_game_count": dev_data[
                        "total_games_count"
                    ],  # Includes descendants
                    "parent_id": parent_id,
                    "level": level,
                    "child_ids": child_ids,
                    "is_last_child": is_last,
                    "continues_at_levels": list(continues_at_levels),
                }
            )

            # For children: if this item is NOT the last, add current level to continues
            child_continues = continues_at_levels + ([level] if not is_last else [])

            # Recursively flatten sub-developers
            flat.extend(
                self.flatten_developers(
                    dev_data["sub_developers"],
                    parent_id=dev_data["developer"].id,
                    level=level + 1,
                    continues_at_levels=child_continues,
                )
            )
        return flat

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        developer = context["developer"]

        # Try to get cached context first
        cached = self._get_cached_context(developer)
        if cached is not None:
            if (
                isinstance(cached, dict)
                and cached.get("cache_schema_version") == self.CACHE_SCHEMA_VERSION
            ):
                all_game_ids = cached.get("all_game_ids", [])
                all_games, games_by_id = self._fetch_games_by_ids(all_game_ids)
                developer_ids = self._collect_developer_ids(
                    cached.get("subsidiaries_serialized", [])
                )
                developers_by_id = models.Developer.objects.in_bulk(developer_ids)
                root_game_ids = cached.get("root_game_ids", [])
                root_games = [
                    games_by_id[gid] for gid in root_game_ids if gid in games_by_id
                ]
                subsidiaries_with_games = self._hydrate_subsidiaries(
                    cached.get("subsidiaries_serialized", []),
                    games_by_id,
                    developers_by_id,
                )

                context.update(
                    {
                        "subsidiaries_with_games": subsidiaries_with_games,
                        "root_games": root_games,
                        "total_games": cached.get("total_games", 0),
                        "subsidiaries_count": cached.get("subsidiaries_count", 0),
                        "developers_flat": cached.get("developers_flat", []),
                        "all_games": all_games,
                        "developer_game_map_json": cached.get(
                            "developer_game_map_json", "{}"
                        ),
                        "developer_child_map_json": cached.get(
                            "developer_child_map_json", "{}"
                        ),
                        "game_rank_map_json": cached.get("game_rank_map_json", "{}"),
                        "game_data_map_json": cached.get("game_data_map_json", "{}"),
                        "game_developer_map": cached.get("game_developer_map", {}),
                        "rank_distribution": cached.get("rank_distribution", []),
                        "max_rank": cached.get("max_rank", 0),
                    }
                )
            else:
                context.update(cached)
            return context

        # Before the rows are read, so a change during the build is not saved
        # over its own invalidation. `get_object` read this one already.
        self._cache_generation = current_generation(GENERATION_DEVELOPERS)
        developer.refresh_from_db()
        self._prefetch_hierarchy(developer)

        # Recursively gather subsidiaries with nested structure
        def gather_subsidiaries(parent_dev, visited=None):
            """Recursively gather subsidiaries and their games."""
            if visited is None:
                visited = set()

            if parent_dev.id in visited:
                return []
            visited.add(parent_dev.id)

            devs_data = []
            for sub_dev in parent_dev.subsidiaries.all():
                dev_games = list(sub_dev.developed_games.all())

                # Recursively get sub-subsidiaries
                sub_devs = gather_subsidiaries(sub_dev, visited)

                # Filter out games that belong to sub-developers
                # (show at most specific level)
                if sub_devs:

                    def collect_sub_game_ids(devs):
                        """Recursively collect all game IDs from sub-developers."""
                        ids = set()
                        for d in devs:
                            ids.update(g.id for g in d["games"])
                            ids.update(collect_sub_game_ids(d["sub_developers"]))
                        return ids

                    sub_game_ids = collect_sub_game_ids(sub_devs)
                    dev_games = [g for g in dev_games if g.id not in sub_game_ids]

                # Only include developers that have games OR sub-developers
                if dev_games or sub_devs:
                    dev_games.sort(key=lambda g: (g.rank or 999999))

                    # Calculate total unique games including all nested developers
                    def calc_total_games(games, sub_devs_list):
                        """Count unique games to prevent double-counting."""
                        game_ids = {g.id for g in games}
                        for sub in sub_devs_list:
                            sub_ids = calc_unique_game_ids(
                                sub["games"], sub["sub_developers"]
                            )
                            game_ids.update(sub_ids)
                        return len(game_ids)

                    def calc_unique_game_ids(games, sub_devs_list):
                        """Recursively collect unique game IDs."""
                        game_ids = {g.id for g in games}
                        for sub in sub_devs_list:
                            game_ids.update(
                                calc_unique_game_ids(
                                    sub["games"], sub["sub_developers"]
                                )
                            )
                        return game_ids

                    # Calculate total nested developers
                    def calc_total_devs(sub_devs_list):
                        total = len(sub_devs_list)
                        for sub in sub_devs_list:
                            total += calc_total_devs(sub["sub_developers"])
                        return total

                    devs_data.append(
                        {
                            "developer": sub_dev,
                            "games": dev_games,
                            "games_count": len(dev_games),
                            "sub_developers": sub_devs,
                            "total_games_count": calc_total_games(dev_games, sub_devs),
                            "total_developers_count": calc_total_devs(sub_devs),
                        }
                    )

            # Sort by total_games_count descending at each level
            devs_data.sort(key=lambda d: d["total_games_count"], reverse=True)
            return devs_data

        # Get root developer's direct games
        root_games = list(developer.developed_games.all())

        # Get all subsidiaries recursively
        subsidiaries_with_games = gather_subsidiaries(developer)

        # Filter out games from root that belong to subsidiaries
        if subsidiaries_with_games:

            def collect_all_sub_game_ids(devs):
                """Recursively collect all game IDs from sub-developers."""
                ids = set()
                for d in devs:
                    ids.update(g.id for g in d["games"])
                    ids.update(collect_all_sub_game_ids(d["sub_developers"]))
                return ids

            sub_game_ids = collect_all_sub_game_ids(subsidiaries_with_games)
            root_games = [g for g in root_games if g.id not in sub_game_ids]

        root_games.sort(key=lambda g: (g.rank or 999999))

        # Count unique games across all developers
        def collect_unique_game_ids(devs):
            """Recursively collect unique game IDs across all developers."""
            game_ids = set()
            for dev_data in devs:
                game_ids.update(g.id for g in dev_data["games"])
                game_ids.update(collect_unique_game_ids(dev_data["sub_developers"]))
            return game_ids

        total_games = len(collect_unique_game_ids(subsidiaries_with_games)) + len(
            root_games
        )

        # Count unique developers (flatten the hierarchy)
        def count_devs(devs):
            total = len(devs)
            for dev_data in devs:
                total += count_devs(dev_data["sub_developers"])
            return total

        subsidiaries_count = count_devs(subsidiaries_with_games)

        context["subsidiaries_with_games"] = subsidiaries_with_games
        context["total_games"] = total_games
        # Include root developer in count (+1) to match filter selection
        context["subsidiaries_count"] = subsidiaries_count + 1

        # Add flattened developer data for filter UI
        devs_flat = self.flatten_developers(subsidiaries_with_games)

        # Prepend root developer as root node for the checkbox tree
        all_top_level_dev_ids = [s["id"] for s in devs_flat if s["level"] == 0]
        all_game_ids = collect_unique_game_ids(subsidiaries_with_games)
        all_game_ids.update(g.id for g in root_games)
        # Root entry only stores ROOT'S DIRECT GAMES (not all games)
        # This ensures proper counting when all children are selected
        root_game_ids = [g.id for g in root_games]
        root_entry = {
            "id": 0,  # Special ID for root (DB IDs start at 1)
            "name": developer.name,
            "game_ids": root_game_ids,  # Only root's direct games
            "total_game_count": len(all_game_ids),  # Total including all descendants
            "level": 0,
            "child_ids": all_top_level_dev_ids,
        }

        # Increment all developer levels by 1 (root is now level 0)
        for dev in devs_flat:
            dev["level"] += 1

        # Insert root at the beginning
        devs_flat.insert(0, root_entry)

        context["developers_flat"] = devs_flat

        # Collect all unique games for filter view
        all_games, games_by_id = self._fetch_games_by_ids(all_game_ids)
        all_games.sort(key=lambda g: (g.rank is None, g.rank or 0, g.id))
        context["all_games"] = all_games

        # The tree above was built from id-and-rank instances; render the
        # fully related ones instead.
        context["root_games"] = [
            games_by_id[g.id] for g in root_games if g.id in games_by_id
        ]
        self._swap_in_games(subsidiaries_with_games, games_by_id)

        # Build developer -> game IDs mapping for Alpine.js
        # Each developer maps to ONLY its direct games (not descendants)
        # JavaScript handles hierarchical selection by checking/unchecking children
        dev_game_map = {}
        for dev in devs_flat:
            dev_game_map[dev["id"]] = dev["game_ids"]

        # Build developer -> child IDs mapping for Alpine.js
        dev_child_map = {d["id"]: d["child_ids"] for d in devs_flat}

        # Serialize to JSON for Alpine.js
        import json
        from django.core.serializers.json import DjangoJSONEncoder

        context["developer_game_map_json"] = json.dumps(
            dev_game_map, cls=DjangoJSONEncoder
        )
        context["developer_child_map_json"] = json.dumps(
            dev_child_map, cls=DjangoJSONEncoder
        )

        # Game rank map for JavaScript to calculate filtered rank distribution
        game_rank_map = {game.id: game.rank for game in all_games if game.rank}
        context["game_rank_map_json"] = json.dumps(game_rank_map, cls=DjangoJSONEncoder)

        # Game data map with playtime for sorting
        game_data_map = {}
        for game in all_games:
            game_data_map[game.id] = {
                "pt": playtime.shown_hours(game.primary_hltb_game_data)
            }
        context["game_data_map_json"] = json.dumps(game_data_map, cls=DjangoJSONEncoder)

        # Build game -> developer IDs map for anchor links
        # This maps each game_id to the list of developer_ids that have it
        game_developer_map = {}
        for dev_id, game_ids in dev_game_map.items():
            for game_id in game_ids:
                if game_id not in game_developer_map:
                    game_developer_map[game_id] = []
                game_developer_map[game_id].append(dev_id)
        context["game_developer_map"] = game_developer_map

        # Rank distribution for visualization - uses global max rank for consistency
        # with the games list page (same bin structure across all pages)
        max_rank = (
            models.Game.objects.filter(rank__isnull=False).aggregate(
                max_rank=Max("rank")
            )["max_rank"]
            or 0
        )

        rank_bins = []
        if max_rank > 0:
            bin_count = config.RANK_DISTRIBUTION_BIN_COUNT
            bin_size = math.ceil(max_rank / bin_count)
            for i in range(bin_count):
                bin_start = i * bin_size + 1
                bin_end = min((i + 1) * bin_size, max_rank)
                count = sum(
                    1 for g in all_games if g.rank and bin_start <= g.rank <= bin_end
                )
                rank_bins.append(
                    {"binStart": bin_start, "binEnd": bin_end, "count": count}
                )

        context["rank_distribution"] = rank_bins
        context["max_rank"] = max_rank
        context["rank_distribution_bin_count"] = config.RANK_DISTRIBUTION_BIN_COUNT

        # Cache the expensive context data (excluding objects that can't be cached)
        # We cache everything that's JSON-serializable or simple Python objects
        serialized_subsidiaries = self._serialize_subsidiaries(subsidiaries_with_games)
        all_game_ids_ordered = [game.id for game in all_games]
        cacheable_context = {
            "cache_schema_version": self.CACHE_SCHEMA_VERSION,
            "subsidiaries_serialized": serialized_subsidiaries,
            "root_game_ids": root_game_ids,
            "all_game_ids": all_game_ids_ordered,
            "total_games": total_games,
            "subsidiaries_count": context["subsidiaries_count"],
            "developers_flat": devs_flat,
            "developer_game_map_json": context["developer_game_map_json"],
            "developer_child_map_json": context["developer_child_map_json"],
            "game_rank_map_json": context["game_rank_map_json"],
            "game_data_map_json": context["game_data_map_json"],
            "game_developer_map": game_developer_map,
            "rank_distribution": rank_bins,
            "max_rank": max_rank,
            "rank_distribution_bin_count": config.RANK_DISTRIBUTION_BIN_COUNT,
        }
        self._set_cached_context(developer, cacheable_context)

        return context


class DeveloperRedirectView(View):
    """
    Redirects developer by ID to the root developer's detail page.
    Handles legacy /developer-alias/:id/ URLs.
    """

    def get(self, request, id):
        developer = get_object_or_404(models.Developer, id=id)
        root = developer.root_developer
        return redirect("developer-detail", slug=root.slug, permanent=True)
