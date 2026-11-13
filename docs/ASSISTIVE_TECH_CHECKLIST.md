# Assistive technology and iPhone checklist

Not planned: the owner said on 2026-11-13 that this run will not be done,
and `ROADMAP.md` lists it under "Known, not planned". The script stays for
anyone who does pick it up. The year grid, the mobile filter sheet, the
search comboboxes and music's listen menu were checked by keyboard, with
axe-core and against Chrome's accessibility tree, but never with a screen
reader or on a real iPhone. None of this can run in CI, so it is a person's
job. Note what you hear or see next to each step, then file anything that
fails as an open bug in `ROADMAP.md`.

Each section runs on both sites: `games.acclaimedmedia.org/` and
`music.acclaimedmedia.org/`. Production works fine for this, since nothing
here writes anything except the filters in the URL.

## What the markup promises

So you know what "right" sounds like:

- **Year grid** (`core/includes/_year_grid.html`): one `role="group"` labelled
  "Release year". Each decade label and each year is a `role="button"` with
  `aria-pressed` and a label such as "1990s, 42 albums" or "1994, 7 games".
  There is one tab stop (roving `tabindex`), and the keys are those in
  `onGridKeydown` (`core/static/core/js/filter-subcomponents.js`): the arrows
  move, Home goes to the row's decade, End to its last year, Enter or Space
  picks, and Shift with Enter or Space extends the range.
- **Mobile sheet** (`_mobile_filter_sheet.html` in games and music):
  `role="dialog"`, `aria-modal="true"`, labelled by its "Filters" heading.
  Opening it moves focus into the sheet, Tab is trapped inside it, Escape
  closes it, and closing it returns focus to the Filters button. The genre
  rows are `role="button"` with `aria-pressed`, and the category toggles have
  `aria-expanded`. The sheet has no year grid. Its Time section
  (`core/includes/_mobile_filter_time.html`) has a header button with
  `aria-expanded`, then a "Pick years by" group of three buttons (Decade /
  Year / Range), then a "Decade" group of decade buttons, a "Year" select, or
  "From year" and "To year" selects. The switch and the decade buttons carry
  `aria-pressed` (added 2026-11-02; before that they showed it by colour
  alone).

- **Search boxes** (`games/templates/includes/_sidebar.html` and
  `_nav_mobile.html`; the keys are `searchComboboxState` in
  `games/static/games/js/utils-base.js`), since 2026-11-10: the field is a
  `role="combobox"` whose `aria-controls` names a `role="listbox"` labelled
  "Search results". The results are `role="option"` links in a
  `role="group"` per kind ("Games", "Developers", "Series"; "Artists",
  "Albums"). Down and Up move an active option, which the field names with
  `aria-activedescendant` while keeping the focus; they wrap. Enter follows
  the active option, or with none goes to the full search as it always did.
  Escape closes the results. The links are still tabbable. This was checked
  against Chrome's accessibility tree only: a combobox that reads wrongly is
  worse than the field and links it replaced, so if these rows fail, revert
  the commit that added it rather than patch it blind.

## 1. VoiceOver on macOS, Safari

Turn it on with Cmd+F5. VO means Control+Option.

| # | Step | Expected | Result |
|---|------|----------|--------|
| 1.1 | Desktop width. Tab to the year grid | "Release year, group", then a decade or year with its count and "toggle button" | |
| 1.2 | Arrow right, down, Home, End | Each step reads the new cell's label. Empty cells are skipped | |
| 1.3 | Enter on a decade | Reads as selected or pressed. The results heading changes | |
| 1.4 | Move to a year in another decade, then Shift+Enter | The range is extended. Do the years inside it read as pressed? | |
| 1.5 | Change the filter, then VO+U for the rotor's headings | The page heading names the filter, e.g. "Most Acclaimed Albums of the 1990s" | |
| 1.6 | Does anything announce the new result count after a filter change? | Unknown: there is no live region. Note what you hear | |
| 1.7 | Narrow the window below 962px. Activate "Filters" | "Filters, dialog", with focus inside the sheet | |
| 1.8 | Tab through the sheet | Focus stays inside it and wraps | |
| 1.9 | Expand Time, Genres and Status. Pick one of each | The genre categories read expanded or collapsed, and the genre rows read pressed. So do the Time section's switch and its decades | |
| 1.10 | Escape | The sheet closes, and focus is back on the Filters button | |
| 1.11 | Desktop width. Tab to the sidebar's search field | "Search games, developers, and series" (or "albums and artists"), "combo box" | |
| 1.12 | Type three letters of a known title, wait a moment | Is anything said when results arrive? The field should now read as expanded | |
| 1.13 | Down arrow, several times | Each result is read with its group the first time ("Games, group"), e.g. "Portal 2007 • #12". Focus stays in the field | |
| 1.14 | Up arrow past the first result | Wraps to the last, "See all ... results" | |
| 1.15 | Enter on a result | Its page opens | |
| 1.16 | Back. Type again, then Escape, then Enter | Escape closes the results; Enter goes to the full search, `/?q=...` | |
| 1.17 | Type again, then Tab instead of the arrows | Focus moves through the result links as before | |

## 2. VoiceOver on iOS Safari, on a real iPhone

Settings, Accessibility, VoiceOver. Swipe right moves to the next item, and a
double tap activates it.

| # | Step | Expected | Result |
|---|------|----------|--------|
| 2.1 | Without VoiceOver: open the sheet, scroll it, close it | The page behind does not scroll. The sheet's own list scrolls smoothly. Nothing jumps when the keyboard opens for the search box | |
| 2.2 | Without VoiceOver: pick a decade in the sheet's Time section, then switch to Range and use From and To | The native picker opens, and the list updates when it closes | |
| 2.3 | Without VoiceOver: on an iPad or in landscape at 962px or wider, use the sidebar's year grid by tapping and dragging | The range shows as one shape, and the list updates | |
| 2.4 | With VoiceOver: swipe to "Filters" and double tap | "Filters, dialog". Swiping stays inside the sheet | |
| 2.5 | Swipe through the Time section's switch and decade buttons, then double tap one | The selected one is announced as selected or pressed | |
| 2.6 | Switch to Year and to Range, then use the selects | "Year", "From year" and "To year" are read, and the picker announces the chosen value | |
| 2.7 | Swipe through the genre tree, expand a category, pick a genre | expanded/collapsed and selected read correctly | |
| 2.8 | Close the sheet with its Close button | Focus lands on the Filters button, not at the top of the page | |
| 2.9 | Rotate to landscape with the sheet open | The sheet stays usable | |
| 2.10 | With VoiceOver: open the search from the top bar, type, then swipe right through the results | The field reads as a combo box; each result is reachable by swiping and opens on a double tap | |

## 3. NVDA on Windows, Firefox and Chrome

NVDA starts in browse mode, so press NVDA+Space to switch to focus mode when
you reach the grid.

| # | Step | Expected | Result |
|---|------|----------|--------|
| 3.1 | Tab to the year grid | "Release year grouping", then the cell as a "toggle button", with whether it is pressed | |
| 3.2 | In focus mode: the arrows, Home, End | Each step reads the new cell. In browse mode the arrows read the page instead, which is expected | |
| 3.3 | Enter, then Shift+Enter on a later year | Pressed states update and are read | |
| 3.4 | Browse mode: H to the heading after a filter change | It names the filter | |
| 3.5 | Narrow window: open the sheet | "Filters dialog". Tab stays inside it. Escape closes it and focus returns | |
| 3.6 | Tab to the sidebar's search field, type, then Down and Up | "combo box", then each option read as the arrows move, with "1 of N" where NVDA gives it. Enter opens it; Escape closes the list | |
| 3.7 | Repeat 3.1-3.6 in the other browser | Same | |

## Afterwards

Write the date, devices and versions here, move what failed into
`ROADMAP.md`, and take its line out of "Known, not planned" there once
every row has a result.
