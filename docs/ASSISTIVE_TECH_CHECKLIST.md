# Assistive technology and iPhone checklist

The open bug "Never tested on real assistive tech or a real iPhone" in
`ROADMAP.md`. The year grid and the mobile filter sheet were checked in
Chrome, WebKit and Firefox, plus Chrome's accessibility tree, but never with a
screen reader or on a real iPhone. None of this can run in CI, so it is a
person's job. Note what you hear or see next to each step, then file anything
that fails as an open bug in `ROADMAP.md`.

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
| 3.6 | Repeat 3.1-3.5 in the other browser | Same | |

## Afterwards

Write the date, devices and versions here, move what failed into
`ROADMAP.md`, and remove the open bug there once every row has a result.
