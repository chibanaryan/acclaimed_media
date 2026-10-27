"""The source lists page: every published list behind the rankings."""

from django.db.models import Case, Count, Q, When, Value, IntegerField
from django.db.models.functions import Lower
from django.views.generic import ListView

from core.mixins import HTMXPartialMixin, RobustPaginationMixin
from games import constants, models


class ListListView(RobustPaginationMixin, HTMXPartialMixin, ListView):
    """
    Source Lists page - displays lists grouped by publication.

    Publications are paginated (30 per page) and can be sorted by:
    - importance (default): weighted score based on list type counts
    - alpha: alphabetical by name

    Lists within each publication are sorted by type importance
    (All-time > Decade > Misc > EOY) then by year descending.
    """

    model = models.Publication
    template_name = "lists/list_list.html"
    context_object_name = "publication_groups"
    paginate_by = 50
    paginate_orphans = 0
    htmx_partial_template = "lists/includes/_list_list_content.html"

    def get_template_names(self):
        # Append mode for Load More (publication grouping only)
        if self.request.GET.get("append") == "true":
            _, _, _, _, group_by = self._get_list_filters()
            if group_by == "publication":
                return ["lists/includes/_list_list_append.html"]
        return super().get_template_names()

    def _get_list_filters(self):
        """Parse and validate filter parameters from request."""
        year_value = self.request.GET.get("year")
        type_slug = self.request.GET.get("type")
        search_query = self.request.GET.get("q", "").strip()
        group_by_param = self.request.GET.get("group_by")

        try:
            year_value = int(year_value) if year_value else None
        except (ValueError, TypeError):
            year_value = None

        type_code = constants.LIST_TYPE_CODES.get(type_slug) if type_slug else None

        # Auto-determine grouping from type filter unless explicitly overridden.
        # This restores flat type-grouped results when a list type is selected.
        if group_by_param is None or group_by_param.strip() == "":
            group_by = "type" if type_code else "publication"
        else:
            group_by = group_by_param.strip().lower()
            if group_by not in ("publication", "type"):
                group_by = "publication"

        return year_value, type_slug, type_code, search_query, group_by

    def _get_filtered_list_queryset(self, year_value, type_code):
        """Build base list queryset with filters applied."""
        qs = models.List.objects.all()
        if year_value:
            qs = qs.filter(year=year_value)
        if type_code:
            qs = qs.filter(type=type_code)
        return qs

    def _build_type_group_context(
        self,
        context,
        year_value,
        type_slug,
        type_code,
        search_query,
        sort,
        sort_direction,
        group_by,
    ):
        """Build context for type-grouped view.

        Groups lists by type (All-time, Decade, Misc, EOY), showing a flat
        list of all lists within each type section.
        """
        type_groups = []
        grand_total_lists = 0

        for type_code_iter in constants.LIST_TYPE_IMPORTANCE_ORDER:
            type_label = constants.get_list_type_label(type_code_iter)

            # Skip if filtering by type and this isn't the selected type
            if type_code and type_code != type_code_iter:
                continue

            # Build list queryset for this type
            lists_qs = models.List.objects.filter(type=type_code_iter)
            if year_value:
                lists_qs = lists_qs.filter(year=year_value)
            if search_query:
                lists_qs = lists_qs.filter(publisher__name__icontains=search_query)

            # Select related publisher for efficient access
            lists_qs = lists_qs.select_related("publisher")

            total_list_count = lists_qs.count()
            if total_list_count == 0:
                continue

            grand_total_lists += total_list_count

            # Apply sorting
            if sort == "alpha":
                # Sort by publication name, then list name
                if sort_direction == "asc":
                    lists_qs = lists_qs.order_by(
                        Lower("publisher__name"), Lower("name")
                    )
                else:
                    lists_qs = lists_qs.order_by(
                        Lower("publisher__name").desc(), Lower("name").desc()
                    )
            else:  # "release" - sort by year
                if sort_direction == "desc":
                    lists_qs = lists_qs.order_by(
                        "-year", Lower("publisher__name"), Lower("name")
                    )
                else:
                    lists_qs = lists_qs.order_by(
                        "year", Lower("publisher__name"), Lower("name")
                    )

            # Load all lists for this type
            lists = list(lists_qs)

            type_groups.append(
                {
                    "type_code": type_code_iter,
                    "type_label": type_label,
                    "lists": lists,
                    "total_count": total_list_count,
                }
            )

        # --- FACETED COUNTS FOR FILTERS ---
        # Year counts: filtered by type only (NOT year)
        year_base_qs = models.List.objects.all()
        if type_code:
            year_base_qs = year_base_qs.filter(type=type_code)

        list_year_counts = list(
            year_base_qs.values("year").annotate(count=Count("id")).order_by("-year")
        )

        year_str = str(year_value) if year_value else None
        filtered_years = [
            y for y in list_year_counts if y["count"] > 0 or str(y["year"]) == year_str
        ]

        # Type counts: filtered by year only (NOT type)
        type_base_qs = models.List.objects.all()
        if year_value:
            type_base_qs = type_base_qs.filter(year=year_value)

        type_counts_raw = list(
            type_base_qs.values("type").annotate(count=Count("id")).order_by("type")
        )

        filtered_types = []
        for t in type_counts_raw:
            t["slug"] = constants.LIST_TYPE_SLUGS.get(t["type"], t["type"])
            if t["count"] > 0 or t["type"] == type_code:
                filtered_types.append(t)

        filtered_types.sort(
            key=lambda t: constants.LIST_TYPE_PRIORITY.get(t["type"], 99)
        )

        # Build context
        context["type_groups"] = type_groups
        context["meta"] = {"lists": {"years": filtered_years}}
        context["list_types"] = constants.LIST_TYPES
        context["type_counts"] = filtered_types
        context["filters"] = {
            "year": str(year_value) if year_value else None,
            "type": type_slug,
            "q": search_query,
        }
        context["sort"] = sort
        context["sort_direction"] = sort_direction
        context["group_by"] = group_by
        # Grand total: all lists (filtered by year/search but NOT type)
        grand_total_qs = models.List.objects.all()
        if year_value:
            grand_total_qs = grand_total_qs.filter(year=year_value)
        if search_query:
            grand_total_qs = grand_total_qs.filter(
                publisher__name__icontains=search_query
            )
        context["grand_total_list_count"] = grand_total_qs.count()

        # Sort options for type grouping mode
        context["sort_options"] = [
            ("release", "Year"),
            ("alpha", "Alphabetical"),
        ]

        # Total lists count (filtered by type)
        context["total_list_count"] = grand_total_lists

        return context

    def get_queryset(self):
        """Get publications with list counts, filtered and sorted."""
        year_value, type_slug, type_code, search_query, group_by = (
            self._get_list_filters()
        )

        # Store group_by for use in get_context_data
        self.group_by = group_by

        # For type grouping, we handle data in get_context_data instead
        if group_by == "type":
            return models.Publication.objects.none()

        raw_sort = self.request.GET.get("sort", "")
        sort = raw_sort if raw_sort in ("importance", "alpha") else "importance"
        # Default direction depends on sort type: desc for importance, asc for alpha
        default_dir = "asc" if sort == "alpha" else "desc"
        sort_direction = self.request.GET.get("dir", default_dir)

        # Base list queryset for filtering
        list_filter = Q()
        if year_value:
            list_filter &= Q(lists__year=year_value)
        if type_code:
            list_filter &= Q(lists__type=type_code)

        # Annotate publications with list counts by type
        # Only count lists that match the current filters
        count_filter = Q()
        if year_value:
            count_filter &= Q(year=year_value)
        if type_code:
            count_filter &= Q(type=type_code)

        # Build filter conditions for badge counts
        # Year filter applies to all counts
        # Type filter: only show count for matching type (others become 0)
        year_filter = Q(lists__year=year_value) if year_value else Q()

        qs = models.Publication.objects.annotate(
            # Filtered counts for display - responsive to both year and type filters
            alltime_count=Count(
                "lists",
                filter=Q(lists__type=constants.LIST_ALLTIME)
                & year_filter
                & (
                    Q()
                    if not type_code or type_code == constants.LIST_ALLTIME
                    else Q(pk__in=[])
                ),
            ),
            decade_count=Count(
                "lists",
                filter=Q(lists__type=constants.LIST_DECADE)
                & year_filter
                & (
                    Q()
                    if not type_code or type_code == constants.LIST_DECADE
                    else Q(pk__in=[])
                ),
            ),
            misc_count=Count(
                "lists",
                filter=Q(lists__type=constants.LIST_MISC)
                & year_filter
                & (
                    Q()
                    if not type_code or type_code == constants.LIST_MISC
                    else Q(pk__in=[])
                ),
            ),
            eoy_count=Count(
                "lists",
                filter=Q(lists__type=constants.LIST_EOY)
                & year_filter
                & (
                    Q()
                    if not type_code or type_code == constants.LIST_EOY
                    else Q(pk__in=[])
                ),
            ),
            # Total filtered count
            total_count=Count("lists", filter=list_filter if list_filter else Q()),
            # Importance score for sorting
            # When type filter is applied: sort by count of that type
            # When no type filter: weighted score
            # (All-time: 1000, Decade: 100, Misc: 10, EOY: 1)
            importance_score=(
                Count("lists", filter=list_filter if list_filter else Q())
                if type_code
                else (
                    Count(
                        "lists",
                        filter=Q(lists__type=constants.LIST_ALLTIME) & year_filter,
                    )
                    * 1000
                    + Count(
                        "lists",
                        filter=Q(lists__type=constants.LIST_DECADE) & year_filter,
                    )
                    * 100
                    + Count(
                        "lists",
                        filter=Q(lists__type=constants.LIST_MISC) & year_filter,
                    )
                    * 10
                    + Count(
                        "lists",
                        filter=Q(lists__type=constants.LIST_EOY) & year_filter,
                    )
                )
            ),
        )

        # Only include publications with matching lists
        qs = qs.filter(total_count__gt=0)

        # Apply search filter if provided
        if search_query:
            qs = qs.filter(name__icontains=search_query)

        # Sort by importance or alphabetically, respecting direction
        if sort == "alpha":
            if sort_direction == "asc":
                qs = qs.order_by(Lower("name"))
            else:
                qs = qs.order_by(Lower("name").desc())
        else:
            # Sort by importance score, then alphabetically as tiebreaker
            if sort_direction == "asc":
                qs = qs.order_by("importance_score", Lower("name"))
            else:
                qs = qs.order_by("-importance_score", Lower("name"))

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        year_value, type_slug, type_code, search_query, group_by = (
            self._get_list_filters()
        )

        # Default sort depends on group_by mode
        # Normalize sort to valid options for the current mode to handle
        # stale values when the type filter switches the grouping mode
        raw_sort = self.request.GET.get("sort", "")
        if group_by == "type":
            sort = raw_sort if raw_sort in ("release", "alpha") else "release"
            default_dir = "desc" if sort == "release" else "asc"
        else:
            sort = raw_sort if raw_sort in ("importance", "alpha") else "importance"
            default_dir = "asc" if sort == "alpha" else "desc"

        sort_direction = self.request.GET.get("dir", default_dir)

        # Handle type grouping mode
        if group_by == "type":
            return self._build_type_group_context(
                context,
                year_value,
                type_slug,
                type_code,
                search_query,
                sort,
                sort_direction,
                group_by,
            )

        # Build the publication groups with their lists
        publication_groups = []
        publications = context.get("publication_groups", [])

        # Build type priority ordering for lists
        type_priority = Case(
            *[
                When(type=code, then=Value(idx))
                for idx, code in enumerate(constants.LIST_TYPE_IMPORTANCE_ORDER)
            ],
            default=Value(99),
            output_field=IntegerField(),
        )

        publication_ids = [pub.id for pub in publications]
        lists_by_publication_id = {}
        if publication_ids:
            lists_qs = models.List.objects.filter(publisher_id__in=publication_ids)
            if year_value:
                lists_qs = lists_qs.filter(year=year_value)
            if type_code:
                lists_qs = lists_qs.filter(type=type_code)

            # Sort by publisher, then type importance, then year descending.
            lists_qs = (
                lists_qs.select_related("publisher")
                .annotate(type_priority=type_priority)
                .order_by("publisher_id", "type_priority", "-year", "name")
            )
            for list_obj in lists_qs:
                lists_by_publication_id.setdefault(list_obj.publisher_id, []).append(
                    list_obj
                )

        for pub in publications:
            publication_groups.append(
                {
                    "publication": pub,
                    "alltime_count": pub.alltime_count,
                    "decade_count": pub.decade_count,
                    "misc_count": pub.misc_count,
                    "eoy_count": pub.eoy_count,
                    "total_count": pub.total_count,
                    "lists": lists_by_publication_id.get(pub.id, []),
                }
            )

        context["publication_groups"] = publication_groups

        # --- FACETED COUNTS FOR FILTERS ---
        # Year counts: filtered by type only (NOT year)
        year_base_qs = models.List.objects.all()
        if type_code:
            year_base_qs = year_base_qs.filter(type=type_code)

        list_year_counts = list(
            year_base_qs.values("year").annotate(count=Count("id")).order_by("-year")
        )

        # Filter years: include count > 0 OR currently selected
        year_str = str(year_value) if year_value else None
        filtered_years = [
            y for y in list_year_counts if y["count"] > 0 or str(y["year"]) == year_str
        ]

        # Type counts: filtered by year only (NOT type)
        type_base_qs = models.List.objects.all()
        if year_value:
            type_base_qs = type_base_qs.filter(year=year_value)

        type_counts_raw = list(
            type_base_qs.values("type").annotate(count=Count("id")).order_by("type")
        )

        # Add slug to each type and filter: include count > 0 OR currently selected
        filtered_types = []
        for t in type_counts_raw:
            t["slug"] = constants.LIST_TYPE_SLUGS.get(t["type"], t["type"])
            if t["count"] > 0 or t["type"] == type_code:
                filtered_types.append(t)

        # Sort by importance priority (All-time > Decade > Misc > EOY)
        filtered_types.sort(
            key=lambda t: constants.LIST_TYPE_PRIORITY.get(t["type"], 99)
        )

        # Build context
        context["meta"] = {"lists": {"years": filtered_years}}
        context["list_types"] = constants.LIST_TYPES
        context["type_counts"] = filtered_types
        context["filters"] = {
            "year": str(year_value) if year_value else None,
            "type": type_slug,  # Keep as slug for template comparison
            "q": search_query,
        }
        context["sort"] = sort
        context["sort_direction"] = sort_direction
        context["group_by"] = group_by

        # Sort options for publication grouping mode
        context["sort_options"] = [
            ("importance", "# Lists"),
            ("alpha", "Alphabetical"),
        ]

        # Total list count for display (loaded publications only)
        total_lists = sum(g["total_count"] for g in publication_groups)
        context["total_list_count"] = total_lists

        # Grand total list count across ALL publications (for "X of Y lists")
        grand_total_qs = models.List.objects.all()
        if year_value:
            grand_total_qs = grand_total_qs.filter(year=year_value)
        if type_code:
            grand_total_qs = grand_total_qs.filter(type=type_code)
        context["grand_total_list_count"] = grand_total_qs.count()

        # Load More context (paginating publications)
        page_obj = context.get("page_obj")
        if page_obj:
            context["has_more"] = page_obj.has_next()
            context["next_page"] = (
                page_obj.next_page_number() if page_obj.has_next() else None
            )
            context["total_count"] = page_obj.paginator.count  # Total publications
            context["loaded_count"] = page_obj.end_index()
            context["remaining_count"] = max(
                0, page_obj.paginator.count - page_obj.end_index()
            )

        return context
