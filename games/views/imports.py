"""The staff import page and its progress streams."""

import json
import logging
from pathlib import Path

from django.conf import settings
from django.db.models import Q
from django.forms import Form
from django.http import HttpResponse, HttpResponseForbidden, StreamingHttpResponse
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import FormView

from core.mixins import StaffOnlyMixin
from games import models, utils
from games.forms import ImportForm
from games.services import post_import

logger = logging.getLogger(__name__)


def _with_metadata_note(message):
    """Start the post-import fetch, and say so under the import's message."""
    note = post_import.schedule()
    return f"{message}\n{note}" if note else message


class ImportView(StaffOnlyMixin, FormView):
    """
    Handles batch importing of game data files with validation and transaction safety.

    Supports:
    - Batch upload of multiple TSV files (platforms, lists, games, memberships)
    - Single-file uploads (legacy support)
    - Delete existing data
    - IGDB data fetching

    Files are imported in dependency order:
    1. Platforms (no dependencies)
    2. Source Lists (Publications auto-created)
    3. Games (requires Platforms)
    4. Game Positions (requires Lists and Games)
    """

    template_name = "import.html"
    form_class = ImportForm
    success_url = reverse_lazy("import")

    def get_context_data(self, **kwargs) -> dict:
        """Add database object counts and persistent errors to context."""
        context = super().get_context_data(**kwargs)
        # Staff reload this page to watch a fetch land, so it restarts one a
        # deploy or worker recycle cut short.
        context["metadata_resumed"] = post_import.resume()

        try:
            # Get all counts in a single aggregation query (optimized)
            total_games = models.Game.objects.count()

            # Count metadata records (not games)
            # This persists when games are deleted (metadata is orphaned)
            total_igdb_metadata = models.IGDBGameData.objects.count()
            orphaned_igdb = models.IGDBGameData.objects.filter(
                game__isnull=True
            ).count()
            connected_igdb = total_igdb_metadata - orphaned_igdb

            total_wikipedia_metadata = models.WikipediaGameData.objects.count()
            orphaned_wikipedia = models.WikipediaGameData.objects.filter(
                game__isnull=True
            ).count()
            connected_wikipedia = total_wikipedia_metadata - orphaned_wikipedia

            total_hltb_metadata = models.HLTBGameData.objects.count()
            orphaned_hltb = models.HLTBGameData.objects.filter(
                game__isnull=True
            ).count()
            connected_hltb = total_hltb_metadata - orphaned_hltb

            # Count games that need metadata (for fetch button)
            games_needing_igdb = models.Game.objects.needing_igdb().count()
            games_needing_wikipedia = models.Game.objects.filter(
                Q(primary_wikipedia_game_data__isnull=True)
                | Q(primary_wikipedia_game_data__page_title="")
            ).count()
            games_needing_hltb = models.Game.objects.filter(
                primary_hltb_game_data__isnull=True
            ).count()

            context["counts"] = {
                "platforms": models.Platform.objects.count(),
                "publications": models.Publication.objects.count(),
                "lists": models.List.objects.count(),
                "games": total_games,
                "memberships": models.ListMembership.objects.count(),
                "developers": models.Developer.objects.count(),
                "series": models.Series.objects.count(),
                "wikipedia_genres": models.WikipediaGenre.objects.count(),
            }
            # Calculate time estimates for fetching metadata
            # IGDB: ~8-10 games/sec with default settings
            igdb_estimate_seconds = (
                int(games_needing_igdb / 9) if games_needing_igdb > 0 else 0
            )

            # Wikipedia: depends on authentication
            # Optimized to reuse page URLs from lookup (2 network requests per game)
            # Authenticated: ~1.0 games/sec, Unauthenticated: ~0.4 games/sec
            from django.conf import settings

            has_wikidata_auth = bool(getattr(settings, "WIKIDATA_ACCESS_TOKEN", None))
            wiki_games_per_sec = 1.0 if has_wikidata_auth else 0.4
            wiki_estimate_seconds = (
                int(games_needing_wikipedia / wiki_games_per_sec)
                if games_needing_wikipedia > 0
                else 0
            )

            context["igdb_counts"] = {
                "total": total_igdb_metadata,
                "connected": connected_igdb,
                "orphaned": orphaned_igdb,
                "games_needing": games_needing_igdb,
                "percentage": int(
                    (connected_igdb / total_igdb_metadata * 100)
                    if total_igdb_metadata > 0
                    else 0
                ),
                "estimate_seconds": igdb_estimate_seconds,
            }
            context["wikipedia_counts"] = {
                "total": total_wikipedia_metadata,
                "connected": connected_wikipedia,
                "orphaned": orphaned_wikipedia,
                "games_needing": games_needing_wikipedia,
                "percentage": int(
                    (connected_wikipedia / total_wikipedia_metadata * 100)
                    if total_wikipedia_metadata > 0
                    else 0
                ),
                "estimate_seconds": wiki_estimate_seconds,
                "has_auth": has_wikidata_auth,
            }
            context["hltb_counts"] = {
                "total": total_hltb_metadata,
                "connected": connected_hltb,
                "orphaned": orphaned_hltb,
                "games_needing": games_needing_hltb,
                "percentage": int(
                    (connected_hltb / total_hltb_metadata * 100)
                    if total_hltb_metadata > 0
                    else 0
                ),
            }
        except Exception as e:
            # If database queries fail, provide safe defaults so page still loads
            logger.exception("Error loading import page counts")
            context["counts"] = {
                "platforms": 0,
                "publications": 0,
                "lists": 0,
                "games": 0,
                "memberships": 0,
                "developers": 0,
                "series": 0,
                "wikipedia_genres": 0,
            }
            context["igdb_counts"] = {
                "total": 0,
                "connected": 0,
                "orphaned": 0,
                "games_needing": 0,
                "percentage": 0,
                "estimate_seconds": 0,
            }
            context["wikipedia_counts"] = {
                "total": 0,
                "connected": 0,
                "orphaned": 0,
                "games_needing": 0,
                "percentage": 0,
                "estimate_seconds": 0,
                "has_auth": False,
            }
            context["hltb_counts"] = {
                "total": 0,
                "connected": 0,
                "orphaned": 0,
                "games_needing": 0,
                "percentage": 0,
            }
            context["import_errors"] = [
                f"Error loading page data: {e}. The database may be in an "
                "inconsistent state."
            ]
            context["import_success_message"] = None
            return context

        # Get persistent errors from session
        import_errors = self.request.session.pop("import_errors", None)
        import_success_message = self.request.session.pop("import_success", None)
        context["import_errors"] = import_errors
        context["import_success_message"] = import_success_message

        return context

    def form_valid(self, form: Form) -> HttpResponse:
        """Process the import form and handle file uploads."""
        import_data = form.cleaned_data

        # Quick action: load bundled test data files from the repo
        if import_data.get("seed_test_data"):
            seed_dir = Path(settings.BASE_DIR) / "acclaimedgames" / "test_input_files"
            file_map = {
                "platforms_file": "PlatformDB.txt",
                "lists_file": "SourceLists.txt",
                "games_file": "Top1400.txt",
                "memberships_file": "GamePositions.txt",
            }

            opened_files = {}
            try:
                for field, filename in file_map.items():
                    path = seed_dir / filename
                    opened_files[field] = open(path, "rb")

                seed_payload = {**import_data, **opened_files}
                res, message = utils.import_batch(seed_payload)
            except FileNotFoundError:
                res, message = (
                    False,
                    (
                        "Bundled test data files not found in "
                        "acclaimedgames/test_input_files."
                    ),
                )
            finally:
                for fh in opened_files.values():
                    fh.close()

            if res:
                self.request.session["import_success"] = _with_metadata_note(
                    "Loaded bundled test data.\n" + message
                )
            else:
                self.request.session["import_errors"] = [message]

            self.request.session.modified = True
            return super().form_valid(form)

        # Check if this is a batch file import (not delete/igdb operations)
        has_batch_files = any(
            [
                import_data.get("platforms_file"),
                import_data.get("lists_file"),
                import_data.get("games_file"),
                import_data.get("memberships_file"),
            ]
        )

        # Uploaded batch files always take precedence over maintenance actions.
        if has_batch_files:
            # Process batch import immediately
            res, message = utils.import_batch(import_data)
            if res:
                # A lists-only import leaves the games as they were.
                if import_data.get("games_file"):
                    message = _with_metadata_note(message)
                # Store success message in session (persist across redirect)
                self.request.session["import_success"] = message
            else:
                # Store error message in session as a list for persistent display
                self.request.session["import_errors"] = [message]
            # Explicitly save session before redirect
            self.request.session.modified = True
            return super().form_valid(form)

        # For maintenance operations, use the standard import flow
        res, message = utils.import_data(import_data)
        if res:
            # Store success message in session (persist across redirect)
            self.request.session["import_success"] = message
        else:
            # Store error message in session as a list for persistent display
            self.request.session["import_errors"] = [message]

        # Explicitly save session before redirect
        self.request.session.modified = True
        return super().form_valid(form)


class StreamFromThisSiteMixin:
    """A GET that starts a job is answered only to this site's own page.

    `EventSource` can only GET, so the two streams below start their work
    on one. A browser sends the session cookie with a link followed from
    another site (`SameSite=Lax` covers a top-level GET), so a staff member
    clicking such a link started a refresh, a forced one if it said so.
    Browsers name where a request came from in `Sec-Fetch-Site`, and the
    import page's `EventSource` is "same-origin". A request without the
    header is let through: every current browser sends it, and one that
    does not (Safari before 16.4) would otherwise lose the page's buttons.
    """

    def dispatch(self, request, *args, **kwargs):
        origin = request.headers.get("Sec-Fetch-Site")
        if request.method == "GET" and origin not in (None, "same-origin"):
            return HttpResponseForbidden(
                "This stream is opened by the import page.", content_type="text/plain"
            )
        return super().dispatch(request, *args, **kwargs)


class IGDBProgressView(StaffOnlyMixin, StreamFromThisSiteMixin, View):
    """
    Streams IGDB data fetching progress via Server-Sent Events (SSE).
    Allows real-time progress bar updates in the browser.
    """

    def get(self, request, *args, **kwargs):
        """Stream IGDB fetch progress as SSE events."""
        update_relationships = (
            request.GET.get("update_relationships", "false").lower() == "true"
        )
        force_refresh = request.GET.get("force", "false").lower() == "true"
        return StreamingHttpResponse(
            utils.import_igdb_with_progress(
                update_relationships=update_relationships,
                force_refresh=force_refresh,
            ),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )


class WikipediaPageProgressView(StaffOnlyMixin, StreamFromThisSiteMixin, View):
    """
    Streams Wikipedia page lookup progress via Server-Sent Events (SSE).
    Allows real-time progress bar updates in the browser.
    """

    def get(self, request, *args, **kwargs):
        """Stream Wikipedia page lookup progress as SSE events."""
        force_refresh = request.GET.get("force", "false").lower() == "true"
        return StreamingHttpResponse(
            utils.import_wikipedia_pages_with_progress(force_refresh=force_refresh),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )


class BatchImportProgressView(StaffOnlyMixin, View):
    """
    Streams batch file import progress via Server-Sent Events (SSE).

    Accepts POST requests with file uploads and streams progress in real-time.
    This prevents Gunicorn timeout for large imports by keeping the connection alive.
    """

    def post(self, request, *args, **kwargs):
        """Stream batch import progress as SSE events."""
        import_data = {
            "platforms_file": request.FILES.get("platforms_file"),
            "lists_file": request.FILES.get("lists_file"),
            "games_file": request.FILES.get("games_file"),
            "memberships_file": request.FILES.get("memberships_file"),
        }

        # Check if any files were provided
        if not any(import_data.values()):

            def error_generator():
                payload = {"event": "error", "message": "No files provided"}
                yield f"data: {json.dumps(payload)}\n\n"

            return StreamingHttpResponse(
                error_generator(),
                content_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        return StreamingHttpResponse(
            utils.import_batch_with_progress(import_data),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
