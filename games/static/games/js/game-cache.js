/**
 * Acclaimed Games - IndexedDB Cache Manager
 *
 * Manages caching of game data in IndexedDB for client-side filtering.
 * A copy is current only if its version is the one the page names.
 */

/**
 * GameDataCache - IndexedDB cache for game data
 *
 * Usage:
 *   const cache = new GameDataCache();
 *   const data = await cache.getData();
 *   // data contains { games, developers, platforms, genres }
 */
class GameDataCache {
    constructor() {
        this.DB_NAME = 'acclaimedgames_v2';  // New name to avoid upgrade issues from v1
        this.DB_VERSION = 1;
        this.STORE_NAME = 'gamedata';
        this.CACHE_KEY = 'allgames';
        this.DATA_URL = '/api/games/all/';
        this._db = null;
        this._initPromise = null;
        // The version of the payload getData last returned
        this.dataVersion = null;
    }

    /**
     * Initialize IndexedDB connection
     * @private
     */
    async _initDB() {
        if (this._db) return this._db;
        if (this._initPromise) return this._initPromise;

        this._initPromise = new Promise((resolve, reject) => {
            // Timeout to prevent infinite hang on corrupted databases
            const timeout = setTimeout(() => {
                console.warn('[GameDataCache] IndexedDB open timed out');
                reject(new Error('IndexedDB timeout'));
            }, 5000);

            const request = indexedDB.open(this.DB_NAME, this.DB_VERSION);

            request.onerror = () => {
                clearTimeout(timeout);
                console.error('IndexedDB error:', request.error);
                reject(request.error);
            };

            request.onsuccess = () => {
                clearTimeout(timeout);
                this._db = request.result;
                resolve(this._db);
            };

            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                if (!db.objectStoreNames.contains(this.STORE_NAME)) {
                    db.createObjectStore(this.STORE_NAME, { keyPath: 'key' });
                }
            };

            request.onblocked = () => {
                clearTimeout(timeout);
                console.warn('[GameDataCache] IndexedDB blocked - close other tabs');
                reject(new Error('IndexedDB blocked'));
            };
        }).catch(err => {
            // Reset promise on failure so future calls can retry
            this._initPromise = null;
            throw err;
        });

        return this._initPromise;
    }

    /**
     * Get cached data from IndexedDB
     * @private
     */
    async _getCached() {
        try {
            const db = await this._initDB();
            return new Promise((resolve, reject) => {
                const transaction = db.transaction(this.STORE_NAME, 'readonly');
                const store = transaction.objectStore(this.STORE_NAME);
                const request = store.get(this.CACHE_KEY);

                request.onerror = () => reject(request.error);
                request.onsuccess = () => resolve(request.result);
            });
        } catch (e) {
            console.warn('IndexedDB read error:', e);
            return null;
        }
    }

    /**
     * Store data in IndexedDB
     * @private
     */
    async _setCached(version, data) {
        try {
            const db = await this._initDB();
            return new Promise((resolve, reject) => {
                const transaction = db.transaction(this.STORE_NAME, 'readwrite');
                const store = transaction.objectStore(this.STORE_NAME);
                const request = store.put({
                    key: this.CACHE_KEY,
                    version,
                    data,
                    timestamp: Date.now()
                });

                request.onerror = () => reject(request.error);
                request.onsuccess = () => resolve();
            });
        } catch (e) {
            console.warn('IndexedDB write error:', e);
        }
    }

    /**
     * The data version the page names, if it names one
     * @private
     */
    _pageVersion() {
        return (typeof window !== 'undefined' && window.gameDataVersion) || '';
    }

    /**
     * Fetch full game data from server. With the page's version in the URL,
     * so the browser's HTTP cache, which keeps a response for an hour by its
     * URL, holds a copy per version; the server keys on its own version
     * @private
     */
    async _fetchData(pageVersion = '') {
        const url = pageVersion
            ? this.DATA_URL + '?v=' + encodeURIComponent(pageVersion)
            : this.DATA_URL;
        const response = await fetch(url);
        if (!response.ok) throw new Error('Data fetch failed');
        return response.json();
    }

    /**
     * Get game data, using cache if valid
     *
     * @param {Object} options
     * @param {boolean} [options.forceRefresh=false] - Force fetch from server
     * @param {Function} [options.onCacheHit] - Callback when cache is valid
     * @param {Function} [options.onCacheMiss] - Callback when fetching from server
     * @returns {Promise<Object>} Game data { games, developers, platforms, genres }
     */
    async getData(options = {}) {
        const { forceRefresh = false, onCacheHit, onCacheMiss } = options;

        if (forceRefresh) {
            if (onCacheMiss) onCacheMiss();
            const response = await this._fetchData(this._pageVersion());
            const { version, data } = response;
            await this._setCached(version, data);
            this.dataVersion = version;
            return data;
        }

        // Try to get cached data
        const cached = await this._getCached();
        // The version the page was rendered from. The renderer joins the
        // page's rows to the payload's by position, so only that version
        // will do, however fresh another copy is
        const pageVersion = this._pageVersion();

        if (pageVersion && cached && cached.version === pageVersion) {
            if (onCacheHit) onCacheHit(cached.data);
            this.dataVersion = cached.version;
            return cached.data;
        }

        // Cache miss or stale - fetch fresh data
        if (onCacheMiss) onCacheMiss();

        const response = await this._fetchData(pageVersion);
        const { version, data } = response;

        // Store in cache, under the version it names: a payload that still
        // differs from the page's is used, and the next page asks again. Its
        // version is kept, since such a payload cannot continue the page's
        // rows (ClientSideFiltering.followsPage)
        await this._setCached(version, data);
        this.dataVersion = version;

        return data;
    }

    /**
     * Clear the cache
     */
    async clearCache() {
        try {
            const db = await this._initDB();
            return new Promise((resolve, reject) => {
                const transaction = db.transaction(this.STORE_NAME, 'readwrite');
                const store = transaction.objectStore(this.STORE_NAME);
                const request = store.delete(this.CACHE_KEY);

                request.onerror = () => reject(request.error);
                request.onsuccess = () => resolve();
            });
        } catch (e) {
            console.warn('Cache clear error:', e);
        }
    }

    /**
     * Get cache info (for debugging)
     */
    async getCacheInfo() {
        const cached = await this._getCached();
        if (!cached) return null;

        return {
            version: cached.version,
            timestamp: new Date(cached.timestamp),
            gameCount: cached.data?.games?.length || 0,
            sizeEstimate: this._estimateSize(cached.data)
        };
    }

    /**
     * Estimate data size in bytes
     * @private
     */
    _estimateSize(data) {
        try {
            return new Blob([JSON.stringify(data)]).size;
        } catch (e) {
            return 0;
        }
    }
}

// Export for use in other modules
if (typeof window !== 'undefined') {
    window.GameDataCache = GameDataCache;
}
