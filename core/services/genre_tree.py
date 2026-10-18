"""Descendant maps for the self-parented genre trees.

Every section's genre taxonomy is a `parent` FK to itself, and every section
wants the same two things from it: the ids below a given genre, and those ids
for the whole table at once. Walking it through the ORM is what made
`/music/` cost 418 identical `music_musicgenre` selects:
`prefetch_related("children")` populates the rows it fetched, but the child
instances it hands back carry no prefetch of their own, so recursing into
`child.children.all()` is a fresh query per node visited.

One `(id, parent_id)` fetch and an in-memory walk answers it for the entire
table instead. The shape is the one `games.api.views.AlbumAllDataView`'s
sibling already proved for `WikipediaGenre`; it lives here so music, games
and books can share one copy rather than keep three.
"""

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple


def descendants_by_id(
    pairs: Iterable[Tuple[int, Optional[int]]],
) -> Dict[int, List[int]]:
    """Map every node id to the ids beneath it, depth first, excluding itself.

    ``pairs`` is any iterable of ``(id, parent_id)``. Excluding self is the
    primitive because that is what the ``/api/music/all/`` payload's ``"d"``
    key sends; a caller wanting it included writes
    ``[node_id, *result.get(node_id, ())]``.

    Children keep the order they arrive in, so passing a queryset ordered the
    way the model's ``Meta.ordering`` orders it reproduces what
    ``self.children.all()`` used to return, element for element. The mapping
    itself also iterates in that same arrival order, so a caller that walks
    it produces what walking ``Model.objects`` produced.
    """
    children_by_parent: Dict[int, List[int]] = defaultdict(list)
    node_ids: List[int] = []
    for node_id, parent_id in pairs:
        node_ids.append(node_id)
        if parent_id is not None:
            children_by_parent[parent_id].append(node_id)

    result: Dict[int, List[int]] = {}
    # Iterative and memoized: `result` doubles as the memo, so the whole
    # table costs one pass rather than one walk per node. `in_progress`
    # guards against a parent cycle - bad data that would otherwise spin a
    # web worker forever, where the recursive version raised RecursionError.
    for root_id in node_ids:
        if root_id in result:
            continue
        stack: List[Tuple[int, bool]] = [(root_id, False)]
        in_progress = set()
        while stack:
            node_id, expanded = stack.pop()
            if expanded:
                in_progress.discard(node_id)
                descendants: List[int] = []
                for child_id in children_by_parent.get(node_id, ()):
                    descendants.append(child_id)
                    descendants.extend(result.get(child_id, ()))
                result[node_id] = descendants
                continue
            if node_id in result or node_id in in_progress:
                continue
            in_progress.add(node_id)
            stack.append((node_id, True))
            for child_id in reversed(children_by_parent.get(node_id, ())):
                stack.append((child_id, False))

    # The walk resolves a node after its children, so `result` is in
    # post-order. Rebuild it in arrival order: callers iterate this to count
    # or render a tree, and doing that in the order the rows came in is what
    # keeps their output identical to the per-instance walk it replaces.
    return {node_id: result[node_id] for node_id in node_ids}


def fetch_descendants_by_id(queryset) -> Dict[int, List[int]]:
    """``descendants_by_id`` over one ``values_list("id", "parent_id")`` query.

    The queryset's ordering is what fixes the order of each node's children,
    so pass one whose ordering you mean - usually the manager's default, which
    carries the model's ``Meta.ordering``.
    """
    return descendants_by_id(queryset.values_list("id", "parent_id"))
