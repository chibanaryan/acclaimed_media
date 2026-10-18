/**
 * Acclaimed Albums - Client-Side Album List Renderer
 *
 * Renders album rows by cloning the <template> elements music/home.html
 * declares, which hold the same `_album_row.html` partial the server renders
 * rows with. That shared partial is the single source of truth for the
 * markup; this file only fills its data-slot hooks. Changing one without the
 * other is what the dual-rendering section of CLAUDE.md warns about.
 *
 * Extends BaseMediaListRenderer from core, which owns paging, load-more,
 * highlight scrolling and the result summary.
 */
class AlbumListRenderer extends BaseMediaListRenderer {
    /**
     * @param {AlbumFilterEngine} filterEngine - Engine with reference data
     */
    constructor(filterEngine) {
        super(filterEngine);
    }

    /**
     * Grab the row templates on first render.
     * @protected
     */
    _initTemplates() {
        if (this._templates) return;

        this._templates = {
            desktop: document.getElementById('desktop-row-template'),
            mobile: document.getElementById('mobile-row-template'),
            grid: document.getElementById('grid-card-template')
        };

        if (!this._templates.desktop || !this._templates.mobile) {
            // Nothing can be rendered without them. The caller leaves the
            // server-rendered rows alone when render() returns nothing.
            console.warn('Album row templates not found; keeping server-rendered rows');
            this._templates = null;
        }
    }

    /**
     * Render one grid card, cloning the same `_album_card_grid.html` the
     * server renders cards with.
     * @protected
     * @returns {Element|null}
     */
    _renderGridCard(compactAlbum, index, showRank) {
        this._initTemplates();
        if (!this._templates || !this._templates.grid) return null;

        const card = this._templates.grid.content.cloneNode(true).firstElementChild;
        if (!card) return null;

        const album = this.engine.expandAlbum(compactAlbum);
        const url = `/music/${encodeURIComponent(album.slug)}/`;

        card.id = `music-${album.id}-grid`;
        if (this.highlightId && album.id === this.highlightId) {
            card.classList.add('is-highlighted');
        }

        // The grid badge carries a # that the row's rank column does not,
        // so the rank pair is filled here rather than through _fillRanks.
        const rank = card.querySelector('[data-slot="rank-grid"]');
        if (rank && showRank !== 'none') {
            rank.textContent = `#${showRank === 'filtered' ? index : album.rank}`;
        }
        const globalRank = card.querySelector('[data-slot="global-rank-grid"]');
        if (globalRank) {
            globalRank.textContent = `#${album.rank}`;
            globalRank.classList.toggle('hidden', showRank !== 'filtered');
        }

        this._fillCover(card, album, 'cover', 'cover-placeholder');
        const coverLink = card.querySelector('[data-slot="cover-link"]');
        if (coverLink) coverLink.href = url;

        this._fillSlot(card, 'name-grid', album.name);
        const titleLink = card.querySelector('[data-slot="title-link-grid"]');
        if (titleLink) titleLink.href = url;
        this._fillSlot(card, 'year-grid', album.year === null ? '' : album.year);

        this._fillSlot(card, 'creator', album.artistCredit || '');
        const genres = card.querySelector('[data-slot="genres-grid"]');
        if (genres) {
            genres.textContent = album.genres.map(genre => genre.n).join(' / ');
        }
        const listCount = card.querySelector('[data-slot="list-count-grid"]');
        if (listCount) {
            const label = album.listCount === 1 ? 'list' : 'lists';
            listCount.textContent = album.listCount
                ? `${album.listCount} ${label}`
                : '';
        }

        return card;
    }

    /**
     * Point the cover <img> at an album's art, or show the placeholder.
     *
     * Both elements are always in the row - see the comment in
     * `_album_row.html` - so this is a matter of filling one and hiding the
     * other, in whichever direction the album needs.
     * @private
     */
    _fillCover(row, album, imgSlot, placeholderSlot) {
        const img = row.querySelector(`[data-slot="${imgSlot}"]`);
        const placeholder = row.querySelector(`[data-slot="${placeholderSlot}"]`);

        if (img && album.thumbnail) {
            img.src = album.thumbnail;
            img.alt = album.name;
            img.classList.remove('hidden');
        } else if (img) {
            img.removeAttribute('src');
            img.classList.add('hidden');
        }

        if (placeholder) {
            placeholder.classList.toggle('hidden', Boolean(album.thumbnail));
        }
    }

    /**
     * Fill the rank pair, matching the server's show_rank handling.
     * @private
     */
    _fillRanks(row, album, index, showRank, slot, globalSlot) {
        if (showRank === 'none') return;

        this._fillSlot(row, slot, showRank === 'filtered' ? index : album.rank);

        if (!globalSlot) return;
        const globalRank = row.querySelector(`[data-slot="${globalSlot}"]`);
        if (!globalRank) return;
        // The all-time rank in parentheses only means something when the
        // visible rank is a position within the filtered set.
        globalRank.textContent = `(#${album.rank})`;
        globalRank.classList.toggle('hidden', showRank !== 'filtered');
    }

    /**
     * The artists as links, falling back to the published credit.
     *
     * Mirrors the `artist_links` template tag: an album whose credit was
     * never parsed into artists, or whose artists have no slug, shows the
     * published text rather than nothing.
     * @private
     * @returns {string} HTML
     */
    _artistCreditHtml(album) {
        const linkable = album.artists.filter(artist => artist.s);
        if (!linkable.length) {
            return this._escapeHtml(album.artistCredit || '');
        }
        const separator = '<span class="text-base-content/30">, </span>';
        return linkable
            .map(artist =>
                `<a href="/music/artists/${encodeURIComponent(artist.s)}/" ` +
                `class="link link-hover">${this._escapeHtml(artist.n)}</a>`
            )
            .join(separator);
    }

    /**
     * Build the metadata line's inner HTML.
     *
     * The separators between the parts are conditional server-side, so the
     * line is assembled here rather than slotted piece by piece - the same
     * approach `game-list-renderer.js` takes for its details row.
     * @private
     * @returns {string} HTML
     */
    _metaHtml(album, { withGenres, withCredit = true }) {
        const divider = '<span class="text-base-content/30">|</span> ';
        const parts = [];

        if (withCredit && album.artistCredit) {
            parts.push(
                '<span class="whitespace-nowrap font-medium text-base-content"' +
                ` data-slot="artist-credit">${this._artistCreditHtml(album)}</span>`
            );
        }

        if (withGenres && album.genres.length) {
            // Clickable, as the game row's genres are: each one adds itself
            // to the filter rather than only naming itself.
            const names = album.genres
                .map(genre => {
                    const label = this._escapeHtml(genre.n);
                    return (
                        '<button type="button" class="hover:text-primary ' +
                        'cursor-pointer transition-colors" ' +
                        `onclick="event.stopPropagation(); ` +
                        `document.dispatchEvent(new CustomEvent('add-genre', ` +
                        `{detail: {genreId: '${genre.id}', itemId: ` +
                        `'${album.id}'} }))" title="${label}">${label}</button>`
                    );
                })
                .join('<span class="text-base-content/30"> / </span>');
            parts.push(
                `<span class="whitespace-nowrap">${parts.length ? divider : ''}` +
                `<span data-slot="genres">${names}</span></span>`
            );
        }

        if (album.listCount) {
            const label = album.listCount === 1 ? 'list' : 'lists';
            parts.push(
                `<span class="whitespace-nowrap">${parts.length ? divider : ''}` +
                `<span class="tabular-nums" data-slot="list-count">` +
                `${album.listCount} ${label}</span></span>`
            );
        }

        return parts.join('\n');
    }

    /** @private */
    _fillMeta(row, album, slot, options) {
        const container = row.querySelector(`[data-slot="${slot}"]`);
        if (container) {
            container.innerHTML = this._metaHtml(album, options);
        }
    }

    /**
     * Render one desktop row.
     * @protected
     * @returns {Element|null}
     */
    _renderDesktopRow(compactAlbum, index, showRank) {
        this._initTemplates();
        if (!this._templates) return null;

        const row = this._templates.desktop.content.cloneNode(true).firstElementChild;
        if (!row) return null;

        const album = this.engine.expandAlbum(compactAlbum);
        const url = `/music/${encodeURIComponent(album.slug)}/`;

        // The server renders `music-<id>` here (media_type + id, from the
        // shared row template), and `?highlight=` deep links and the
        // scroll-to-highlight both look rows up by that id.
        row.id = `music-${album.id}`;
        if (this.highlightId && album.id === this.highlightId) {
            const inner = row.querySelector('[data-slot="media-row"]');
            if (inner) inner.classList.add('is-highlighted');
        }

        this._fillRanks(row, album, index, showRank, 'rank', 'global-rank');
        this._fillCover(row, album, 'thumbnail', 'thumbnail-placeholder');

        this._fillSlot(row, 'name', album.name);
        const titleLink = row.querySelector('[data-slot="title-link"]');
        if (titleLink) titleLink.href = url;
        const thumbLink = row.querySelector('[data-slot="thumb-link"]');
        if (thumbLink) thumbLink.href = url;

        const credit = row.querySelector('[data-slot="artist-credit-inline"]');
        if (credit) credit.innerHTML = this._artistCreditHtml(album);

        this._fillSlot(row, 'year', album.year === null ? '' : album.year);
        const yearLink = row.querySelector('[data-slot="year-link"]');
        if (yearLink && album.year !== null) {
            yearLink.href =
                `/music/?start=${album.year}&end=${album.year}` +
                `&highlight=${album.id}`;
        } else if (yearLink) {
            yearLink.removeAttribute('href');
        }
        this._fillMeta(row, album, 'meta-row', {
            withGenres: true,
            withCredit: false
        });

        return row;
    }

    /**
     * Render one mobile row.
     *
     * The mobile row shows the raw published credit and no genres, as
     * `_album_row.html`'s mobile_metadata block does.
     * @protected
     * @returns {Element|null}
     */
    _renderMobileRow(compactAlbum, index, showRank) {
        this._initTemplates();
        if (!this._templates) return null;

        const row = this._templates.mobile.content.cloneNode(true).firstElementChild;
        if (!row) return null;

        const album = this.engine.expandAlbum(compactAlbum);
        const url = `/music/${encodeURIComponent(album.slug)}/`;

        row.id = `music-${album.id}-mobile`;
        row.setAttribute('onclick', `window.location.href='${url}'`);
        if (this.highlightId && album.id === this.highlightId) {
            row.classList.add('is-highlighted');
        }

        if (showRank !== 'none') {
            const rank = showRank === 'filtered' ? index : album.rank;
            this._fillSlot(row, 'rank-mobile', `#${rank}`);
        }
        this._fillCover(row, album, 'thumbnail-mobile', 'thumbnail-mobile-placeholder');

        // The title sits as a bare text node between the rank and the year,
        // so it is written directly rather than through a slot of its own.
        const title = row.querySelector('[data-slot="title-mobile"]');
        const yearEl = row.querySelector('[data-slot="year-mobile"]');
        if (yearEl) {
            yearEl.textContent = album.year === null ? '' : `(${album.year})`;
        }
        if (title && yearEl) {
            title.insertBefore(document.createTextNode(` ${album.name} `), yearEl);
        }

        // Mobile credit is the published text, not links.
        const mobileAlbum = Object.assign({}, album, { artists: [] });
        this._fillMeta(row, mobileAlbum, 'meta-mobile', { withGenres: false });

        return row;
    }

    /**
     * Scroll to a highlighted album.
     *
     * Overridden only to use this section's row ids; the base class looks for
     * `item-<id>`.
     * @protected
     */
    _scrollToHighlight(albumId) {
        const desktop = document.getElementById(`music-${albumId}`);
        const mobile = document.getElementById(`music-${albumId}-mobile`);
        const target = window.matchMedia('(min-width: 962px)').matches
            ? desktop || mobile
            : mobile || desktop;
        if (!target) return;

        setTimeout(() => {
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            [desktop, mobile].forEach(el => {
                if (el) el.classList.add('is-highlighted');
            });
        }, 300);
    }

    /**
     * Result summary, worded exactly as the shared controls partial words it
     * server-side - which is also how the games rankings page words it.
     * @returns {string} HTML
     */
    getResultSummaryHtml(loaded, total, options = {}) {
        if (!total) return '';
        if (options.compact) {
            // The mobile line drops the "Showing" and the element id, which
            // only ever belongs to one element on the page.
            return (
                '<span class="loaded-count-value">' + loaded.toLocaleString() +
                '</span> of ' + total.toLocaleString()
            );
        }
        return (
            'Showing <span id="loaded-count" class="loaded-count-value">' +
            loaded.toLocaleString() + '</span> of ' + total.toLocaleString()
        );
    }

    /**
     * Load-more button, matching `_album_load_more.html` - and so the games
     * load-more - in both wording and classes.
     * @returns {string} HTML
     */
    getLoadMoreHtml(state) {
        const { hasMore, remaining } = state;
        if (!hasMore) return '';
        return (
            '<button type="button" class="btn btn-ghost load-more-button">' +
            '<span class="mdi mdi-album"></span>' +
            '<span class="load-more-text">Load More (' +
            remaining.toLocaleString() + ' remaining)</span></button>'
        );
    }
}

/**
 * The data-slot hooks this renderer fills in a cloned row, declared rather
 * than left implicit so music/tests/test_visual_regression.py can check that
 * `_album_row.html` still emits every one of them - in the empty rendering
 * as well as a filled one.
 *
 * `artist-credit`, `genres` and `list-count` are deliberately absent: those
 * live inside the metadata line, which is written as innerHTML because its
 * separators are conditional, so they exist only in a row that has them.
 */
AlbumListRenderer.SLOTS = [
    'root',
    'media-row',
    'artist-credit-inline',
    'rank',
    'global-rank',
    'thumb-link',
    'thumbnail',
    'thumbnail-placeholder',
    'title-link',
    'name',
    'year',
    'meta-row',
    'root-mobile',
    'rank-mobile',
    'thumbnail-mobile',
    'thumbnail-mobile-placeholder',
    'title-mobile',
    'year-mobile',
    'meta-mobile'
];

/** The slots the grid card renderer fills, checked the same way. */
AlbumListRenderer.GRID_SLOTS = [
    'root-grid',
    'rank-container',
    'rank-grid',
    'global-rank-grid',
    'cover-link',
    'cover',
    'cover-placeholder',
    'overlay',
    'creator',
    'genres-grid',
    'list-count-grid',
    'title-link-grid',
    'name-grid',
    'year-grid'
];

if (typeof window !== 'undefined') {
    window.AlbumListRenderer = AlbumListRenderer;
}
