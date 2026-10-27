(function () {
    "use strict";

    var SHARED_PLATFORM_HIERARCHY_UI = {
        nintendo: {
            name: "Nintendo",
            icon: "mdi-nintendo-switch",
            formFactors: {
                home: {
                    name: "Home Consoles",
                    platforms: ["NES", "FDS", "SNES", "N64", "GC", "Wii", "WiiU", "SW", "SW2"],
                },
                handheld: {
                    name: "Handhelds",
                    platforms: ["GW", "GB", "GBC", "GBA", "DS", "3DS"],
                },
            },
        },
        playstation: {
            name: "PlayStation",
            icon: "mdi-sony-playstation",
            formFactors: {
                home: {
                    name: "Home Consoles",
                    platforms: ["PS", "PS2", "PS3", "PS4", "PS5", "PSVR"],
                },
                handheld: {
                    name: "Handhelds",
                    platforms: ["PSP", "PSV"],
                },
            },
        },
        xbox: {
            name: "Xbox",
            icon: "mdi-microsoft-xbox",
            platforms: ["Xbox", "X360", "XB1", "XBXS"],
        },
        sega: {
            name: "Sega",
            svgIcon: "platform-sega",
            formFactors: {
                home: {
                    name: "Home Consoles",
                    platforms: ["SMS", "GEN", "SCD", "SAT", "DC"],
                },
                handheld: {
                    name: "Handhelds",
                    platforms: ["GG"],
                },
            },
        },
        pc: {
            name: "PC",
            icon: "mdi-microsoft-windows",
            platforms: ["WIN", "DOS", "LIN", "MAC"],
        },
        arcadePlus: {
            name: "Arcade, Mobile, & VR",
            icon: "mdi-space-invaders",
            platforms: ["ARC", "AND", "iOS", "LMD", "VR", "BR"],
        },
        retro: {
            name: "Retro Consoles",
            icon: "mdi-pac-man",
            platforms: ["A26", "A52", "A78", "INTV", "CV", "TG16", "3DO", "NG", "JAG", "LYNX", "NGP", "VECT", "WS"],
        },
        computers: {
            name: "Microcomputers",
            icon: "mdi-desktop-classic",
            formFactors: {
                commodore: { name: "Commodore", platforms: ["VC20", "C64", "AMI", "CD32"] },
                uk: { name: "UK", platforms: ["ZXS", "CPC", "BBCM", "ARCH", "D32"] },
                japan: { name: "Japan", platforms: ["PC88", "PC98", "FM7", "FMT", "SX1", "MSX", "TT"] },
                atari: { name: "Atari", platforms: ["A8", "AST"] },
                other: { name: "Other", platforms: ["A2", "T80", "TCC", "PDP", "HP21", "E60", "MIC"] },
            },
        },
    };

    function createEnginePlatformHierarchy(uiHierarchy) {
        var result = {};
        Object.keys(uiHierarchy).forEach(function (mfrKey) {
            var mfr = uiHierarchy[mfrKey];
            var allCodes = [];
            var mapped = {
                name: mfr.name,
            };

            if (mfr.formFactors) {
                mapped.formFactors = {};
                Object.keys(mfr.formFactors).forEach(function (ffKey) {
                    var ff = mfr.formFactors[ffKey];
                    var ffCodes = (ff.platforms || []).slice();
                    mapped.formFactors[ffKey] = {
                        name: ff.name,
                        codes: ffCodes,
                    };
                    allCodes = allCodes.concat(ffCodes);
                });
            }

            if (mfr.platforms) {
                allCodes = allCodes.concat(mfr.platforms.slice());
            }

            mapped.codes = Array.from(new Set(allCodes));
            result[mfrKey] = mapped;
        });
        return result;
    }

    if (typeof window !== "undefined" && !window.AV_PLATFORM_HIERARCHY) {
        window.AV_PLATFORM_HIERARCHY = createEnginePlatformHierarchy(SHARED_PLATFORM_HIERARCHY_UI);
    }

    function createPlatformHierarchy() {
        return JSON.parse(JSON.stringify(SHARED_PLATFORM_HIERARCHY_UI));
    }

    function defineComputed(target, key, getter) {
        Object.defineProperty(target, key, {
            configurable: true,
            enumerable: true,
            get: getter,
        });
    }

    function createPlatformFilterComponent(config) {
        var filters = config.filters;
        var platforms = config.platforms;
        // Platforms never change after the page renders - only their filtered
        // counts do - so the lookups are built once. Every row's bindings used
        // to scan the reactive array with find(); a year change re-evaluates
        // every row, so one filter change paid for hundreds of full scans.
        var indexByCode = indexBy(platforms, function (p) {
            return p.code;
        });
        var indexById = indexBy(platforms, function (p) {
            return String(p.id);
        });
        var idsByManufacturer = {};
        var idsByFormFactor = {};

        function platformById(platformId) {
            var i = indexById[String(platformId)];
            return i === undefined ? undefined : platforms[i];
        }

        return {
            _platformCountsHandler: null,
            _platformGroupCountsHandler: null,
            countsReady: false,
            groupCounts: {},
            expandedManufacturers: {},
            expandedFormFactors: {},
            platformHierarchy: createPlatformHierarchy(),

            init: function () {
                var self = this;
                this._platformCountsHandler = function (event) {
                    self.updateFilteredCounts(event.detail);
                    self.countsReady = true;
                };
                window.addEventListener("platform-counts-update", this._platformCountsHandler);

                this._platformGroupCountsHandler = function (event) {
                    self.groupCounts = event.detail;
                    self.countsReady = true;
                };
                window.addEventListener("platform-group-counts-update", this._platformGroupCountsHandler);
                this.loadExpandedState();
            },

            destroy: function () {
                if (this._platformCountsHandler) {
                    window.removeEventListener("platform-counts-update", this._platformCountsHandler);
                }
                if (this._platformGroupCountsHandler) {
                    window.removeEventListener("platform-group-counts-update", this._platformGroupCountsHandler);
                }
            },

            loadExpandedState: function () {
                try {
                    var savedMfr = localStorage.getItem("platformManufacturersExpanded");
                    var savedFF = localStorage.getItem("platformFormFactorsExpanded");
                    if (savedMfr) {
                        this.expandedManufacturers = JSON.parse(savedMfr);
                    }
                    if (savedFF) {
                        this.expandedFormFactors = JSON.parse(savedFF);
                    }
                } catch (e) {
                    this.expandedManufacturers = {};
                    this.expandedFormFactors = {};
                }
            },

            saveExpandedState: function () {
                localStorage.setItem("platformManufacturersExpanded", JSON.stringify(this.expandedManufacturers));
                localStorage.setItem("platformFormFactorsExpanded", JSON.stringify(this.expandedFormFactors));
            },

            toggleManufacturerExpanded: function (mfrKey) {
                var self = this;
                var newState = !this.expandedManufacturers[mfrKey];
                this.expandedManufacturers[mfrKey] = newState;
                var mfr = this.platformHierarchy[mfrKey];
                if (mfr && mfr.formFactors) {
                    Object.keys(mfr.formFactors).forEach(function (ffKey) {
                        var key = mfrKey + "_" + ffKey;
                        self.expandedFormFactors[key] = newState;
                    });
                }
                this.saveExpandedState();
            },

            isManufacturerExpanded: function (mfrKey) {
                if (this.expandedManufacturers[mfrKey] === undefined) {
                    return this.hasManufacturerOrChildrenSelected(mfrKey);
                }
                return this.expandedManufacturers[mfrKey];
            },

            toggleFormFactorExpanded: function (mfrKey, ffKey) {
                var key = mfrKey + "_" + ffKey;
                this.expandedFormFactors[key] = !this.expandedFormFactors[key];
                this.saveExpandedState();
            },

            isFormFactorExpanded: function (mfrKey, ffKey) {
                var key = mfrKey + "_" + ffKey;
                if (this.expandedFormFactors[key] === undefined) {
                    return this.hasFormFactorSelection(mfrKey, ffKey);
                }
                return this.expandedFormFactors[key];
            },

            updateFilteredCounts: function (countMap) {
                platforms.forEach(function (p) {
                    p.filtered_count = countMap[String(p.id)] || 0;
                });
            },

            getPlatformByCode: function (code) {
                var i = indexByCode[code];
                return i === undefined ? undefined : platforms[i];
            },

            getEffectiveCount: function (platform) {
                if (!platform) {
                    return 0;
                }
                return platform.filtered_count !== undefined
                    ? platform.filtered_count
                    : platform.game_count || 0;
            },

            formatPlatformYears: function (platform) {
                if (!platform || !platform.year_start) {
                    return "";
                }
                var startAbbr = "'" + String(platform.year_start).slice(-2);
                var endAbbr = platform.year_end ? "'" + String(platform.year_end).slice(-2) : "now";
                return "(" + startAbbr + "-" + endAbbr + ")";
            },

            formatPlatformName: function (platform) {
                if (!platform) {
                    return "";
                }
                if (!platform.year_start) {
                    return platform.name;
                }
                var endYear = platform.year_end ? platform.year_end : "now";
                return platform.name + " (" + platform.year_start + "-" + endYear + ")";
            },

            get sortedManufacturerKeys() {
                var self = this;
                return Object.keys(this.platformHierarchy).sort(function (a, b) {
                    return self.getManufacturerTotalCount(b) - self.getManufacturerTotalCount(a);
                });
            },

            getSortedFormFactorKeys: function (mfrKey) {
                var self = this;
                var mfr = this.platformHierarchy[mfrKey];
                if (!mfr || !mfr.formFactors) {
                    return [];
                }
                return Object.keys(mfr.formFactors).sort(function (a, b) {
                    return self.getFormFactorTotalCount(mfrKey, b) - self.getFormFactorTotalCount(mfrKey, a);
                });
            },

            getAllCodesForManufacturer: function (mfrKey) {
                var mfr = this.platformHierarchy[mfrKey];
                if (!mfr) {
                    return [];
                }
                if (mfr.formFactors) {
                    return Object.values(mfr.formFactors).flatMap(function (ff) {
                        return ff.platforms;
                    });
                }
                return mfr.platforms || [];
            },

            getManufacturerTotalCount: function (mfrKey) {
                var self = this;
                if (this.groupCounts && this.groupCounts[mfrKey]) {
                    return this.groupCounts[mfrKey].count || 0;
                }
                var codes = this.getAllCodesForManufacturer(mfrKey);
                return codes.reduce(function (sum, code) {
                    var p = self.getPlatformByCode(code);
                    return sum + self.getEffectiveCount(p);
                }, 0);
            },

            getFormFactorTotalCount: function (mfrKey, ffKey) {
                var self = this;
                if (this.groupCounts && this.groupCounts[mfrKey] && this.groupCounts[mfrKey].formFactors) {
                    return this.groupCounts[mfrKey].formFactors[ffKey] || 0;
                }
                var mfr = this.platformHierarchy[mfrKey];
                if (!mfr || !mfr.formFactors || !mfr.formFactors[ffKey]) {
                    return 0;
                }
                return mfr.formFactors[ffKey].platforms.reduce(function (sum, code) {
                    var p = self.getPlatformByCode(code);
                    return sum + self.getEffectiveCount(p);
                }, 0);
            },

            getFormFactorPlatforms: function (mfrKey, ffKey) {
                var self = this;
                var mfr = this.platformHierarchy[mfrKey];
                if (!mfr || !mfr.formFactors || !mfr.formFactors[ffKey]) {
                    return [];
                }
                return mfr.formFactors[ffKey].platforms
                    .map(function (code) {
                        return self.getPlatformByCode(code);
                    })
                    .filter(function (p) {
                        return p;
                    })
                    .sort(function (a, b) {
                        var startA = a.year_start || 9999;
                        var startB = b.year_start || 9999;
                        if (startA !== startB) {
                            return startA - startB;
                        }
                        var endA = a.year_end || 9999;
                        var endB = b.year_end || 9999;
                        if (endA !== endB) {
                            return endA - endB;
                        }
                        return (a.name || "").localeCompare(b.name || "");
                    });
            },

            getFlatPlatforms: function (mfrKey) {
                var self = this;
                var mfr = this.platformHierarchy[mfrKey];
                if (!mfr || !mfr.platforms) {
                    return [];
                }
                return mfr.platforms
                    .map(function (code) {
                        return self.getPlatformByCode(code);
                    })
                    .filter(function (p) {
                        return p;
                    })
                    .sort(function (a, b) {
                        var startA = a.year_start || 9999;
                        var startB = b.year_start || 9999;
                        if (startA !== startB) {
                            return startA - startB;
                        }
                        var endA = a.year_end || 9999;
                        var endB = b.year_end || 9999;
                        if (endA !== endB) {
                            return endA - endB;
                        }
                        return (a.name || "").localeCompare(b.name || "");
                    });
            },

            isPlatformAvailable: function (platformId) {
                var platform = platformById(platformId);
                if (!platform) {
                    return false;
                }
                var count = this.getEffectiveCount(platform);
                return count > 0 || this.isPlatformInFilter(platformId);
            },

            hasZeroResults: function (platformId) {
                var platform = platformById(platformId);
                if (!platform) {
                    return false;
                }
                var count = this.getEffectiveCount(platform);
                return count === 0 && this.isPlatformInFilter(platformId);
            },

            isManufacturerAvailable: function (mfrKey) {
                var self = this;
                var codes = this.getAllCodesForManufacturer(mfrKey);
                return codes.some(function (code) {
                    var p = self.getPlatformByCode(code);
                    return p && self.isPlatformAvailable(p.id);
                });
            },

            isFormFactorAvailable: function (mfrKey, ffKey) {
                var self = this;
                var mfr = this.platformHierarchy[mfrKey];
                if (!mfr || !mfr.formFactors || !mfr.formFactors[ffKey]) {
                    return false;
                }
                return mfr.formFactors[ffKey].platforms.some(function (code) {
                    var p = self.getPlatformByCode(code);
                    return p && self.isPlatformAvailable(p.id);
                });
            },

            isPlatformInFilter: function (platformId) {
                return filters.platforms.includes(String(platformId));
            },

            findPlatformParent: function (platformId) {
                var id = String(platformId);
                for (var _i = 0, _arr = Object.keys(this.platformHierarchy); _i < _arr.length; _i++) {
                    var mfrKey = _arr[_i];
                    var mfr = this.platformHierarchy[mfrKey];
                    if (mfr.formFactors) {
                        for (var _j = 0, _entries = Object.entries(mfr.formFactors); _j < _entries.length; _j++) {
                            var entry = _entries[_j];
                            var ffKey = entry[0];
                            var ff = entry[1];
                            var platformIds = ff.platforms
                                .map(this.getPlatformByCode.bind(this))
                                .filter(Boolean)
                                .map(function (p) {
                                    return String(p.id);
                                });
                            if (platformIds.includes(id)) {
                                return { mfrKey: mfrKey, ffKey: ffKey };
                            }
                        }
                    } else if (mfr.platforms) {
                        var flatIds = mfr.platforms
                            .map(this.getPlatformByCode.bind(this))
                            .filter(Boolean)
                            .map(function (p) {
                                return String(p.id);
                            });
                        if (flatIds.includes(id)) {
                            return { mfrKey: mfrKey, ffKey: null };
                        }
                    }
                }
                return null;
            },

            _isFormFactorFullySelected: function (mfrKey, ffKey) {
                var platformIds = this.getAllPlatformIdsForFormFactor(mfrKey, ffKey);
                if (platformIds.length === 0) {
                    return false;
                }
                return platformIds.every(function (id) {
                    return filters.platforms.includes(id);
                });
            },

            isPlatformSelected: function (platformId) {
                if (!filters.platforms.includes(String(platformId))) {
                    return false;
                }
                var parentInfo = this.findPlatformParent(platformId);
                if (!parentInfo) {
                    return true;
                }
                if (this.isManufacturerSelected(parentInfo.mfrKey)) {
                    return false;
                }
                if (
                    parentInfo.ffKey &&
                    this._isFormFactorFullySelected(parentInfo.mfrKey, parentInfo.ffKey)
                ) {
                    return false;
                }
                return true;
            },

            togglePlatform: function (platformId) {
                var id = String(platformId);
                var parentInfo = this.findPlatformParent(platformId);
                if (parentInfo) {
                    if (this.isManufacturerSelected(parentInfo.mfrKey)) {
                        var mfrPlatformIds = this.getAllPlatformIdsForManufacturer(parentInfo.mfrKey);
                        filters.platforms = filters.platforms.filter(function (pid) {
                            return !mfrPlatformIds.includes(pid);
                        });
                        filters.platforms.push(id);
                        return;
                    }
                    if (parentInfo.ffKey && this._isFormFactorFullySelected(parentInfo.mfrKey, parentInfo.ffKey)) {
                        var ffPlatformIds = this.getAllPlatformIdsForFormFactor(parentInfo.mfrKey, parentInfo.ffKey);
                        filters.platforms = filters.platforms.filter(function (pid) {
                            return !ffPlatformIds.includes(pid);
                        });
                        filters.platforms.push(id);
                        return;
                    }
                }
                var idx = filters.platforms.indexOf(id);
                if (idx > -1) {
                    filters.platforms.splice(idx, 1);
                } else {
                    filters.platforms.push(id);
                }
            },

            // Fixed for the page's life, like the hierarchy they come from.
            getAllPlatformIdsForManufacturer: function (mfrKey) {
                if (!idsByManufacturer[mfrKey]) {
                    idsByManufacturer[mfrKey] = this.getAllCodesForManufacturer(mfrKey)
                        .map(this.getPlatformByCode.bind(this))
                        .filter(Boolean)
                        .map(function (p) {
                            return String(p.id);
                        });
                }
                return idsByManufacturer[mfrKey].slice();
            },

            getAllPlatformIdsForFormFactor: function (mfrKey, ffKey) {
                var key = mfrKey + "_" + ffKey;
                if (!idsByFormFactor[key]) {
                    var mfr = this.platformHierarchy[mfrKey];
                    if (!mfr || !mfr.formFactors || !mfr.formFactors[ffKey]) {
                        return [];
                    }
                    idsByFormFactor[key] = mfr.formFactors[ffKey].platforms
                        .map(this.getPlatformByCode.bind(this))
                        .filter(Boolean)
                        .map(function (p) {
                            return String(p.id);
                        });
                }
                return idsByFormFactor[key].slice();
            },

            hasManufacturerOrChildrenSelected: function (mfrKey) {
                var platformIds = this.getAllPlatformIdsForManufacturer(mfrKey);
                return platformIds.some(function (id) {
                    return filters.platforms.includes(id);
                });
            },

            hasFormFactorSelection: function (mfrKey, ffKey) {
                var platformIds = this.getAllPlatformIdsForFormFactor(mfrKey, ffKey);
                return platformIds.some(function (id) {
                    return filters.platforms.includes(id);
                });
            },

            isManufacturerSelected: function (mfrKey) {
                var platformIds = this.getAllPlatformIdsForManufacturer(mfrKey);
                if (platformIds.length === 0) {
                    return false;
                }
                return platformIds.every(function (id) {
                    return filters.platforms.includes(id);
                });
            },

            isFormFactorSelected: function (mfrKey, ffKey) {
                if (this.isManufacturerSelected(mfrKey)) {
                    return false;
                }
                var platformIds = this.getAllPlatformIdsForFormFactor(mfrKey, ffKey);
                if (platformIds.length === 0) {
                    return false;
                }
                return platformIds.every(function (id) {
                    return filters.platforms.includes(id);
                });
            },

            toggleManufacturerSelection: function (mfrKey) {
                if (this.expandedManufacturers[mfrKey] === undefined) {
                    this.expandedManufacturers[mfrKey] = this.hasManufacturerOrChildrenSelected(mfrKey);
                }
                var platformIds = this.getAllPlatformIdsForManufacturer(mfrKey);
                if (this.isManufacturerSelected(mfrKey)) {
                    filters.platforms = filters.platforms.filter(function (id) {
                        return !platformIds.includes(id);
                    });
                } else {
                    var newIds = platformIds.filter(function (id) {
                        return !filters.platforms.includes(id);
                    });
                    filters.platforms = filters.platforms.concat(newIds);
                }
            },

            toggleFormFactorSelection: function (mfrKey, ffKey) {
                var key = mfrKey + "_" + ffKey;
                if (this.expandedFormFactors[key] === undefined) {
                    this.expandedFormFactors[key] = this.hasFormFactorSelection(mfrKey, ffKey);
                }
                var platformIds = this.getAllPlatformIdsForFormFactor(mfrKey, ffKey);
                if (this.isManufacturerSelected(mfrKey)) {
                    var mfrPlatformIds = this.getAllPlatformIdsForManufacturer(mfrKey);
                    filters.platforms = filters.platforms.filter(function (id) {
                        return !mfrPlatformIds.includes(id);
                    });
                    filters.platforms = filters.platforms.concat(platformIds);
                    return;
                }
                if (this._isFormFactorFullySelected(mfrKey, ffKey)) {
                    filters.platforms = filters.platforms.filter(function (id) {
                        return !platformIds.includes(id);
                    });
                } else {
                    var newIds = platformIds.filter(function (id) {
                        return !filters.platforms.includes(id);
                    });
                    filters.platforms = filters.platforms.concat(newIds);
                }
            },

            getSelectedCount: function () {
                return filters.platforms.length;
            },

            handleReset: function () {
                this.expandedManufacturers = {};
                this.expandedFormFactors = {};
                localStorage.removeItem("platformManufacturersExpanded");
                localStorage.removeItem("platformFormFactorsExpanded");
            },

            areAllExpanded: function () {
                for (var _i2 = 0, _arr2 = Object.keys(this.platformHierarchy); _i2 < _arr2.length; _i2++) {
                    var mfrKey = _arr2[_i2];
                    if (!this.expandedManufacturers[mfrKey]) {
                        return false;
                    }
                    var mfr = this.platformHierarchy[mfrKey];
                    if (mfr.formFactors) {
                        for (var _j2 = 0, _arr3 = Object.keys(mfr.formFactors); _j2 < _arr3.length; _j2++) {
                            var ffKey = _arr3[_j2];
                            var key = mfrKey + "_" + ffKey;
                            if (!this.expandedFormFactors[key]) {
                                return false;
                            }
                        }
                    }
                }
                return true;
            },

            toggleAllExpanded: function () {
                var shouldExpand = !this.areAllExpanded();
                for (var _i3 = 0, _arr4 = Object.keys(this.platformHierarchy); _i3 < _arr4.length; _i3++) {
                    var mfrKey = _arr4[_i3];
                    this.expandedManufacturers[mfrKey] = shouldExpand;
                    var mfr = this.platformHierarchy[mfrKey];
                    if (mfr.formFactors) {
                        for (var _j3 = 0, _arr5 = Object.keys(mfr.formFactors); _j3 < _arr5.length; _j3++) {
                            var ffKey = _arr5[_j3];
                            this.expandedFormFactors[mfrKey + "_" + ffKey] = shouldExpand;
                        }
                    }
                }
                this.saveExpandedState();
            },
        };
    }

    function createSeriesFilterComponent(config) {
        var filters = config.filters;
        var seriesList = config.seriesList;
        // As for platforms: one lookup instead of a scan per row per update.
        var indexById = indexBy(seriesList, function (s) {
            return String(s.id);
        });

        function seriesById(seriesId) {
            var i = indexById[String(seriesId)];
            return i === undefined ? undefined : seriesList[i];
        }

        return {
            _seriesResetHandler: null,
            _seriesCountsHandler: null,
            searchQuery: "",
            countsReady: false,
            selectedSeries: [],

            init: function () {
                var self = this;
                this.selectedSeries = filters.series || [];
                this._seriesResetHandler = function () {
                    self.handleReset();
                };
                window.addEventListener("series-reset", this._seriesResetHandler);
                this.$watch("filters.series", function (value) {
                    self.selectedSeries = value || [];
                });
                this._seriesCountsHandler = function (event) {
                    self.updateFilteredCounts(event.detail);
                };
                window.addEventListener("series-counts-update", this._seriesCountsHandler);
                setTimeout(function () {
                    self.countsReady = true;
                }, 150);
            },

            destroy: function () {
                if (this._seriesResetHandler) {
                    window.removeEventListener("series-reset", this._seriesResetHandler);
                }
                if (this._seriesCountsHandler) {
                    window.removeEventListener("series-counts-update", this._seriesCountsHandler);
                }
            },

            handleReset: function () {
                this.selectedSeries = [];
                this.searchQuery = "";
            },

            updateFilteredCounts: function (countMap) {
                seriesList.forEach(function (s) {
                    s.filtered_count = countMap[String(s.id)] || 0;
                });
            },

            getEffectiveCount: function (series) {
                return series.filtered_count !== undefined ? series.filtered_count : series.game_count;
            },

            isSeriesAvailable: function (seriesId) {
                var series = seriesById(seriesId);
                if (!series) {
                    return false;
                }
                var count = this.getEffectiveCount(series);
                return count > 0 || this.isSelected(seriesId);
            },

            hasZeroResults: function (seriesId) {
                var series = seriesById(seriesId);
                if (!series) {
                    return false;
                }
                var count = this.getEffectiveCount(series);
                return count === 0 && this.isSelected(seriesId);
            },

            normalizeSearchText: function (value) {
                var lower = String(value || "").toLowerCase();
                if (typeof lower.normalize !== "function") {
                    return lower;
                }
                return lower.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
            },

            get filteredSeries() {
                var self = this;
                // A copy: sorting seriesList itself wrote every index of the
                // page's reactive array on each read, re-triggering every
                // binding that reads it.
                var list = (seriesList || []).slice();
                if (this.searchQuery) {
                    var query = this.normalizeSearchText(this.searchQuery);
                    list = list.filter(function (s) {
                        return self.normalizeSearchText(s.name).includes(query);
                    });
                }
                list.sort(function (a, b) {
                    var countDiff = self.getEffectiveCount(b) - self.getEffectiveCount(a);
                    if (countDiff !== 0) {
                        return countDiff;
                    }
                    return a.name.localeCompare(b.name);
                });
                return list;
            },

            toggleSeries: function (seriesId) {
                var id = String(seriesId);
                if (this.selectedSeries.includes(id)) {
                    this.selectedSeries = [];
                } else {
                    this.selectedSeries = [id];
                }
                filters.series = this.selectedSeries.slice();
                this.$dispatch("filter-changed", { type: "series", items: this.selectedSeries });
            },

            isSelected: function (seriesId) {
                return this.selectedSeries.includes(String(seriesId));
            },
        };
    }

    function createHltbFilterComponent(config) {
        var filters = config.filters;

        return {
            _hltbCountsHandler: null,
            _hltbResetHandler: null,
            countsReady: false,
            presetCounts: {
                short: 0,
                medium: 0,
                long: 0,
            },
            showCustomRange: false,

            init: function () {
                var self = this;
                this._hltbCountsHandler = function (event) {
                    self.presetCounts = event.detail;
                    self.countsReady = true;
                };
                window.addEventListener("hltb-counts-update", this._hltbCountsHandler);

                this._hltbResetHandler = function () {
                    self.handleReset();
                };
                window.addEventListener("hltb-reset", this._hltbResetHandler);

                this.$watch("filters.hltb_min", function () {
                    self.updateCustomVisibility();
                });
                this.$watch("filters.hltb_max", function () {
                    self.updateCustomVisibility();
                });

                setTimeout(function () {
                    self.countsReady = true;
                }, 150);
            },

            destroy: function () {
                if (this._hltbCountsHandler) {
                    window.removeEventListener("hltb-counts-update", this._hltbCountsHandler);
                }
                if (this._hltbResetHandler) {
                    window.removeEventListener("hltb-reset", this._hltbResetHandler);
                }
            },

            handleReset: function () {
                this.showCustomRange = false;
            },

            updateCustomVisibility: function () {
                var hasValues =
                    (filters.hltb_min !== null && filters.hltb_min !== undefined) ||
                    (filters.hltb_max !== null && filters.hltb_max !== undefined);
                var hasPreset = filters.hltb_preset && filters.hltb_preset !== "custom";
                this.showCustomRange = hasValues && !hasPreset;
            },

            selectPreset: function (preset) {
                if (filters.hltb_preset === preset) {
                    filters.hltb_preset = "";
                    filters.hltb_min = null;
                    filters.hltb_max = null;
                } else {
                    var ranges = {
                        short: [0, 10],
                        medium: [10, 30],
                        long: [30, null],
                    };
                    var parsed = ranges[preset] || [null, null];
                    filters.hltb_preset = preset;
                    filters.hltb_min = parsed[0];
                    filters.hltb_max = parsed[1];
                }
                this.dispatchFilterChange();
            },

            updateSlider: function () {
                if (filters.hltb_min !== null && filters.hltb_min < 0) {
                    filters.hltb_min = 0;
                }
                if (filters.hltb_max !== null && filters.hltb_max < 0) {
                    filters.hltb_max = 0;
                }
                if (filters.hltb_min !== null && filters.hltb_max !== null && filters.hltb_max < filters.hltb_min) {
                    filters.hltb_max = filters.hltb_min;
                }
                filters.hltb_preset = "custom";
                this.dispatchFilterChange();
            },

            setMode: function (mode) {
                if ((filters.hltb_mode || "main") === mode) return;
                filters.hltb_mode = mode;
                // modeOnly lets the parent swap displayed times without re-filtering
                this.dispatchFilterChange({ modeOnly: true });
            },

            dispatchFilterChange: function (extra) {
                this.$dispatch("filter-changed", {
                    modeOnly: !!(extra && extra.modeOnly),
                    type: "hltb",
                    mode: filters.hltb_mode,
                    min: filters.hltb_min,
                    max: filters.hltb_max,
                });
            },

            isPresetActive: function (preset) {
                return filters.hltb_preset === preset;
            },

            getPresetCount: function (preset) {
                // Counts arrive for both modes ({main: {...}, completionist: {...}})
                var mode = filters.hltb_mode === "completionist" ? "completionist" : "main";
                var counts = this.presetCounts[mode] || this.presetCounts;
                return counts[preset] || 0;
            },

            getRangeText: function () {
                var min = filters.hltb_min !== null && filters.hltb_min !== undefined ? filters.hltb_min : 0;
                var max = filters.hltb_max !== null && filters.hltb_max !== undefined ? filters.hltb_max : 100;
                if (max >= 100) {
                    return min + "+ hours";
                }
                return min + "-" + max + " hours";
            },
        };
    }

    function createMobilePlatformFilterComponent(config) {
        var filters = config.filters;
        var component = createPlatformFilterComponent(config || {});
        if (!Array.isArray(filters.platforms)) {
            filters.platforms = [];
        }

        component.expanded = JSON.parse(localStorage.getItem("mobileFilterExpanded_platform") || "true");
        component.expandedManufacturers = {};
        component.expandedFormFactors = {};
        component.groupCounts = {};
        component.countsReady = false;
        component.platformHierarchy = createPlatformHierarchy();

        component.init = function () {
            var self = this;
            this.$watch("expanded", function (val) {
                localStorage.setItem("mobileFilterExpanded_platform", JSON.stringify(val));
            });
            this._platformCountsHandler = function (event) {
                self.updateFilteredCounts(event.detail);
                self.countsReady = true;
            };
            this._platformGroupCountsHandler = function (event) {
                self.groupCounts = event.detail;
                self.countsReady = true;
            };
            window.addEventListener("platform-counts-update", this._platformCountsHandler);
            window.addEventListener("platform-group-counts-update", this._platformGroupCountsHandler);
        };

        component.destroy = function () {
            if (this._platformCountsHandler) {
                window.removeEventListener("platform-counts-update", this._platformCountsHandler);
            }
            if (this._platformGroupCountsHandler) {
                window.removeEventListener("platform-group-counts-update", this._platformGroupCountsHandler);
            }
        };

        component.formatPlatformYears = function (platform) {
            if (!platform || !platform.year_start) {
                return "";
            }
            var startShort = String.fromCharCode(39) + String(platform.year_start).slice(-2);
            if (!platform.year_end) {
                return startShort + "-now";
            }
            if (platform.year_start === platform.year_end) {
                return startShort;
            }
            var endShort = String.fromCharCode(39) + String(platform.year_end).slice(-2);
            return startShort + "-" + endShort;
        };

        component.isManufacturerExpanded = function (mfrKey) {
            return this.expandedManufacturers[mfrKey] === true;
        };

        component.toggleManufacturerExpansion = function (mfrKey) {
            var self = this;
            var newState = !this.isManufacturerExpanded(mfrKey);
            this.expandedManufacturers[mfrKey] = newState;
            var mfr = this.platformHierarchy[mfrKey];
            if (mfr && mfr.formFactors) {
                Object.keys(mfr.formFactors).forEach(function (ffKey) {
                    self.expandedFormFactors[mfrKey + "_" + ffKey] = newState;
                });
            }
        };

        component.isFormFactorExpanded = function (mfrKey, ffKey) {
            return this.expandedFormFactors[mfrKey + "_" + ffKey] === true;
        };

        component.toggleFormFactorExpansion = function (mfrKey, ffKey) {
            var key = mfrKey + "_" + ffKey;
            this.expandedFormFactors[key] = !this.isFormFactorExpanded(mfrKey, ffKey);
        };

        component.selectedCount = function () {
            return filters.platforms.length;
        };

        component.clearPlatforms = function () {
            filters.platforms = [];
        };

        component.resetExpanded = function () {
            this.expandedManufacturers = {};
            this.expandedFormFactors = {};
        };

        component.areAllExpanded = function () {
            for (var _i2 = 0, _arr2 = Object.keys(this.platformHierarchy); _i2 < _arr2.length; _i2++) {
                var mfrKey = _arr2[_i2];
                if (!this.expandedManufacturers[mfrKey]) {
                    return false;
                }
            }
            return true;
        };

        component.toggleAllExpanded = function () {
            var shouldExpand = !this.areAllExpanded();
            for (var _i3 = 0, _arr3 = Object.keys(this.platformHierarchy); _i3 < _arr3.length; _i3++) {
                this.expandedManufacturers[_arr3[_i3]] = shouldExpand;
            }
        };

        return component;
    }

    function createMobileSeriesFilterComponent(config) {
        var filters = config.filters;
        var seriesList = config.seriesList;
        var component = createSeriesFilterComponent(config || {});
        if (!Array.isArray(filters.series)) {
            filters.series = [];
        }

        component.expanded = JSON.parse(localStorage.getItem("mobileFilterExpanded_series") || "true");
        component.searchQuery = "";

        component.init = function () {
            var self = this;
            this.$watch("expanded", function (val) {
                localStorage.setItem("mobileFilterExpanded_series", JSON.stringify(val));
            });
            this.selectedSeries = (filters.series || []).slice();
            this._seriesCountsHandler = function (event) {
                self.updateFilteredCounts(event.detail);
            };
            window.addEventListener("series-counts-update", this._seriesCountsHandler);
        };

        component.destroy = function () {
            if (this._seriesCountsHandler) {
                window.removeEventListener("series-counts-update", this._seriesCountsHandler);
            }
        };

        component.updateFilteredCounts = function (countMap) {
            if (!seriesList) {
                return;
            }
            seriesList.forEach(function (s) {
                s.filtered_count = countMap[String(s.id)] || 0;
            });
        };

        defineComputed(component, "filteredSeries", function () {
            var self = this;
            var list = (seriesList || []).slice();
            if (this.searchQuery) {
                var query = this.normalizeSearchText(this.searchQuery);
                list = list.filter(function (s) {
                    return self.normalizeSearchText(s.name).includes(query);
                });
            }
            list.sort(function (a, b) {
                var countDiff = self.getEffectiveCount(b) - self.getEffectiveCount(a);
                if (countDiff !== 0) {
                    return countDiff;
                }
                return a.name.localeCompare(b.name);
            });
            return list;
        });

        component.isSeriesSelected = function (seriesId) {
            return (filters.series || []).includes(String(seriesId));
        };

        component.isSelected = function (seriesId) {
            return this.isSeriesSelected(seriesId);
        };

        component.toggleSeries = function (seriesId) {
            var id = String(seriesId);
            if (filters.series.includes(id)) {
                filters.series = [];
            } else {
                filters.series = [id];
            }
            this.selectedSeries = filters.series.slice();
        };

        component.isSeriesActive = function () {
            return (filters.series || []).length > 0;
        };

        component.clearSeries = function () {
            filters.series = [];
            this.selectedSeries = [];
            this.searchQuery = "";
        };

        return component;
    }

    function registerFactories() {
        Alpine.data("platformFilterComponent", function (config) {
            return createPlatformFilterComponent(config || {});
        });
        Alpine.data("seriesFilterComponent", function (config) {
            return createSeriesFilterComponent(config || {});
        });
        Alpine.data("hltbFilterComponent", function (config) {
            return createHltbFilterComponent(config || {});
        });

        Alpine.data("mobilePlatformFilterComponent", function (config) {
            return createMobilePlatformFilterComponent(config || {});
        });
        Alpine.data("mobileSeriesFilterComponent", function (config) {
            return createMobileSeriesFilterComponent(config || {});
        });
    }

    document.addEventListener("alpine:init", registerFactories);
})();
