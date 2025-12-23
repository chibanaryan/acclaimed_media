# Work-in-Progress Changes Summary

This branch contains uncommitted work saved from the `main` branch on 2025-12-23.

## Overview

This set of changes includes branding updates, UI improvements, documentation restructuring, and new Claude Code skills setup.

---

## 1. Branding Update: "Acclaimed Games" → "Acclaimed Video Games"

Updated site name across all templates and emails for consistency:

**Files affected:**
- `games/templates/base.html` - Page titles, Open Graph tags, Twitter cards, structured data
- `games/templates/games/game_detail.html` - Page titles and social sharing meta tags
- `games/utils.py` - Email templates (subscription confirmation, post notifications)
- Multiple other templates (404, login, subscribe pages, etc.)

---

## 2. Contact Modal Improvements

Enhanced the contact modal to support pre-filled data when triggered from specific contexts.

**Changes:**
- Contact modal now accepts `data-category` attribute to pre-select category dropdown
- Contact modal now accepts `data-game` attribute to pre-fill message with game name
- Form resets when modal is closed

**Files affected:**
- `games/templates/base.html` - JavaScript for modal handling

---

## 3. "Report Incorrect Data" Button on Game Detail Pages

Added a button on game detail pages allowing users to easily report data issues.

**Features:**
- Appears next to game title
- Pre-selects "Data" category in contact form
- Pre-fills message with "Regarding: [Game Name]"

**Files affected:**
- `games/templates/games/game_detail.html`

---

## 4. Studio Filter Panel Improvements

Improved the developer detail page studio filter to include the parent company as a top-level option.

**Changes:**
- Parent company now appears at level 0 in the hierarchy
- Checking parent company selects/deselects all studios
- Removed "Select All" and "Clear All" buttons (redundant with parent checkbox)
- Improved checkbox sizing (removed `checkbox-sm` class)
- Added visual styling for parent company row (border, font weight)

**Files affected:**
- `games/views.py` - `CompanyDetailView.flatten_studios()` and context building
- `games/templates/developers/includes/_studio_filter_panel.html` - Template updates
- `theme/static_src/src/styles.css` - CSS for parent company styling
- `games/static/games/js/studio-filter.js` - Minor JS update

---

## 5. CSS Fixes

**Contact form outline fix:**
- Added `focus:outline-offset-2` to prevent outline overlapping with text in form inputs

**Files affected:**
- `theme/static_src/src/styles.css`

---

## 6. CLAUDE.md Restructured

Significantly trimmed `CLAUDE.md` by moving detailed workflow instructions into Claude Code skills.

**Changes:**
- Removed inline deployment workflow instructions
- Removed detailed IGDB import command documentation
- Removed detailed Wikipedia metadata command documentation
- Added references to the new skills folder
- Removed DEVLOG section (moved to skill)

**Reduction:** ~520 lines removed, replaced with skill references

---

## 7. New Claude Code Skills (`.claude/skills/`)

Created skill files to hold detailed instructions for specific workflows:

- **deploy/** - Commit, push, and deployment workflows
- **igdb-import/** - IGDB data import and management with performance tuning
- **wikipedia-metadata/** - Wikipedia/Wikidata metadata fetching

---

## 8. New Documentation (`docs/`)

Added comprehensive planning documents:

- **feature-roadmap.md** - Prioritized list of potential features with size estimates and implementation phases
- **agentic-ai-features.md** - Detailed technical exploration of AI/LLM features including LangGraph architecture, semantic search, and conversational discovery

---

## 9. THEME_SYSTEM.md Removed

Deleted `THEME_SYSTEM.md` (168 lines) - content likely consolidated elsewhere or deprecated.

---

## Files Changed Summary

| Category | Files |
|----------|-------|
| Templates | 20 files |
| Python (views, utils) | 2 files |
| CSS | 2 files |
| JavaScript | 1 file |
| Documentation | 3 files (1 deleted) |
| New directories | `.claude/skills/`, `docs/` |

**Total:** ~650 lines removed, ~250 lines added (net reduction of ~400 lines in existing files, plus new docs)
