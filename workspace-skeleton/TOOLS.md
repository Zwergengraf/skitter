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
- `browser_action` also supports `evaluate`:
  - run JavaScript with `script`
  - optional `arg` is passed as the evaluate argument
- `click` also supports direct coordinates (`x`, `y`) in addition to selectors.
- Useful when standard element click actionability fails due to overlays/animations.

---

## File Transfer + Attach Notes

- `transfer_file` can move files between executors.
  - Use `source_machine` / `destination_machine` for cross-machine transfer.
  - Use machine value `api` to move files to/from the API server workspace.
- `attach_file` adds a file to the next assistant message (preferred over inline MEDIA).

---

## Delegation Notes

- `sub_agent` is synchronous.
  - Use it when you want help **inside the current reply**.
  - You wait for the result in the same run.
  - Good for bounded tasks that should finish now.
- `sub_agent_batch` is the same idea, but for several parallel synchronous subtasks in the current run.
- `job_start` is asynchronous background work.
  - Use it when the user should **not wait** for completion in this turn.
  - It returns a `job_id` quickly and the work continues in the background.
  - Follow up with `job_status`, `job_list`, and `job_cancel`.

### Which One to Use?

- Use `sub_agent` when:
  - the user expects an answer now
  - the task is medium-sized and should complete in this run
  - you need the result before writing your final response
- Use `job_start` when:
  - the task may take a long time
  - the task may use many tools
  - the user is fine with a later completion message
  - you can write a complete task spec up front

### Important Behavior

- `sub_agent` is not for overnight or open-ended background work.
- `job_start` is the right tool for longer autonomous work, but it is still budget-limited.
- For `job_start`, write a strong spec:
  - clear task
  - useful context
  - concrete acceptance criteria

---

Add more as I learn the setup.
