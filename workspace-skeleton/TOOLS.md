# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## Path Semantics

- Workspace absolute root in sandbox: `{{WORKSPACE_ROOT}}`
- Relative paths in tools/shell are resolved from `{{WORKSPACE_ROOT}}`
- Absolute paths are treated as literal Linux paths

---

## Browser Tool Notes

- `browser_action` supports pointer-level actions:
  - `hover` (by `selector` or `text`)
  - `move_mouse` (by `x`+`y` or `selector`/`text`)
  - `click_at` (by `x`+`y` or `selector`/`text`)
- `click` also supports direct coordinates (`x`, `y`) in addition to selectors.
- Useful when standard element click actionability fails due to overlays/animations.

---

Add more as I learn the setup.
