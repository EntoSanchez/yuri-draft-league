# Mobile Draft Board — implementation notes

Phone (≤767px) redesign of /draftboard: vertical board, tap action sheet,
filter drawer. Code: `static/mobile-draftboard.js`, `@media` blocks in
`static/mobile.css`, minimal hooks in `templates/draftboard.html`.

## Known edge cases
- **Resize mobile→desktop strands the filter inputs.** The filter drawer MOVES
  the real `#db-*` inputs + the `#db-pool-seg` pool control into itself on first
  open (mobile only). If a user then widens the viewport to ≥768px WITHOUT
  reloading (e.g. DevTools, or a very wide foldable), the desktop `.dbl-filters`
  row reappears empty and those controls stay trapped in the now-hidden drawer
  until reload. Real phones can't hit this (they don't cross 767px live). Accepted
  per the plan's "phone rotating won't hit it" reasoning. If it ever matters, add
  a `matchMedia('(max-width:767px)')` change-listener that tears the drawer down
  above 767px and restores the inputs.

## State exposure
- `_starred` / `_pinned` / `_typeColors` are top-level let/const in the page, so
  they are NOT window properties by default. `draftboard.html` exposes them via
  `Object.defineProperty(window, ...)` GETTERS (not one-time aliases) so the
  external mobile-draftboard.js reads the CURRENT binding — important because
  `_pinned` is reassigned to [] in clearCompare().
