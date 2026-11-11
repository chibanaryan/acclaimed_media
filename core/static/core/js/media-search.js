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
 * loops over `order` to place the groups. `searchGroupOrder`,
 * `FetchManager` and `searchComboboxState` come from games/js/utils-base.js,
 * which every page loads ahead of this file.
 *
 * Only the newest request may write. Each keystroke's request aborts the one
 * before it, and one that was aborted writes nothing, `loading` included:
 * a slow answer for "be" used to replace the results for "beatles", and
 * emptying the box while a request was out brought its results back.
 */
function createMediaSearchData(apiUrl, limits) {
    const groups = Object.keys(limits || {});
    // Outside the returned object, so Alpine does not wrap it
    const requests = new FetchManager();

    const empty = () => {
        const blank = {};
        groups.forEach(group => {
            blank[group] = [];
        });
        return blank;
    };

    return {
        // The arrow keys and the active option: games/js/utils-base.js
        ...searchComboboxState(),
        showMenu: false,
        q: '',
        loading: false,
        // The last search failed (an error status, or offline): said as
        // such, where it read as "No results found"
        failed: false,
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
            // The results are about to change under the active option
            this.clearActiveOption();
            const query = this.q.trim();
            this.failed = false;
            if (query.length < 2) {
                requests.abort();
                this.results = empty();
                this.loading = false;
                return;
            }

            const signal = requests.newRequest();
            this.loading = true;
            const params = new URLSearchParams({ q: query });
            groups.forEach(group => {
                // The endpoints spell their limits `album_limit`,
                // `artist_limit`, and so on.
                params.set(group.replace(/s$/, '') + '_limit', limits[group]);
            });

            try {
                const response = await fetch(`${apiUrl}?${params.toString()}`, {
                    credentials: 'same-origin',
                    signal
                });
                if (!response.ok) throw new Error('search request failed');
                const data = await response.json();
                // Overtaken while it was read: a newer request owns the box
                if (signal.aborted) return;
                const next = empty();
                groups.forEach(group => {
                    next[group] = data[group] || [];
                });
                this.results = next;
                this.order = searchGroupOrder(data.order, groups);
            } catch (e) {
                if (signal.aborted) return;
                console.error('Search error:', e);
                this.results = empty();
                this.order = groups.slice();
                this.failed = true;
            } finally {
                // An aborted request leaves `loading` to whatever replaced it
                if (!signal.aborted) this.loading = false;
            }
        },

        reset() {
            requests.abort();
            this.clearActiveOption();
            this.showMenu = false;
            this.q = '';
            this.loading = false;
            this.failed = false;
            this.results = empty();
            this.order = groups.slice();
        }
    };
}

if (typeof window !== 'undefined') {
    window.createMediaSearchData = createMediaSearchData;
}
