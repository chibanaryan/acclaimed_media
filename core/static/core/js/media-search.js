/**
 * Alpine state for a section's sidebar/navbar search box.
 *
 * The games search box is backed by `createUnifiedSearchData` in
 * games/js/utils-base.js, which speaks in developers, games and series. This
 * is the same idea with the group names left open, so a section can list
 * whatever kinds of thing it has - albums and artists, for music - without a
 * near-copy of that function per section.
 *
 * Usage, from a template:
 *   x-data="createMediaSearchData('{% url 'music-api:unified-search' %}',
 *                                 { artists: 3, albums: 5 })"
 * The keys' order is the groups' order until a response gives one, so it
 * should be the endpoint's tie order (music.api.views.SEARCH_GROUPS).
 * and then read `results.albums` / `results.artists`.
 *
 * An endpoint may also answer with `order`, its group names in the order to
 * show them - it puts whichever group holds the better match first, so
 * "Beatles" leads with the band and "Abbey Road" with the album. A template
 * loops over `order` to place the groups. `searchGroupOrder` comes from
 * games/js/utils-base.js, which every page loads ahead of this file.
 */
function createMediaSearchData(apiUrl, limits) {
    const groups = Object.keys(limits || {});

    const empty = () => {
        const blank = {};
        groups.forEach(group => {
            blank[group] = [];
        });
        return blank;
    };

    return {
        showMenu: false,
        q: '',
        loading: false,
        results: empty(),
        order: groups.slice(),

        /** Whether any group has results, for the "no results" line. */
        hasResults() {
            return groups.some(group => this.results[group].length > 0);
        },

        has(group) {
            return (this.results[group] || []).length > 0;
        },

        async loadResults() {
            const query = this.q.trim();
            if (query.length < 2) {
                this.results = empty();
                this.loading = false;
                return;
            }

            this.loading = true;
            const params = new URLSearchParams({ q: query });
            groups.forEach(group => {
                // The endpoints spell their limits `album_limit`,
                // `artist_limit`, and so on.
                params.set(group.replace(/s$/, '') + '_limit', limits[group]);
            });

            try {
                const response = await fetch(`${apiUrl}?${params.toString()}`, {
                    credentials: 'same-origin'
                });
                if (!response.ok) throw new Error('search request failed');
                const data = await response.json();
                const next = empty();
                groups.forEach(group => {
                    next[group] = data[group] || [];
                });
                this.results = next;
                this.order = searchGroupOrder(data.order, groups);
            } catch (e) {
                console.error('Search error:', e);
                this.results = empty();
                this.order = groups.slice();
            } finally {
                this.loading = false;
            }
        },

        reset() {
            this.showMenu = false;
            this.q = '';
            this.loading = false;
            this.results = empty();
            this.order = groups.slice();
        }
    };
}

if (typeof window !== 'undefined') {
    window.createMediaSearchData = createMediaSearchData;
}
