# CLI and TUI test plan (on a Mac)

The automated tests run against a synthetic database with the step that sends
changes to Things stubbed out. This checklist covers what they can't: the real
Things database, real writes, and a few assumptions about how Things stores
data. It takes about 15 minutes.

Everything below happens inside a throwaway **CLI Test** area, so your own
lists aren't touched. Delete that area at the end (step 6).

## 0. Setup

```bash
git clone https://github.com/pdavisonreiber/things-mcp && cd things-mcp
uv sync --extra tui --extra test   # one sync with both; a later sync with only one removes the other
alias things='uv run things'
```

- [ ] In Things → Settings → General, **Enable Things URLs** is on.
- [ ] `things --version` prints a version.
- [ ] `things today` lists the same to-dos as Today in the Things app, in a
      similar order, with **This Evening** items under their own heading.

> Writes are fire-and-forget: a command returns once macOS has handed the URL
> to Things. If a listing straight after a write doesn't show the change, run
> it again a second later.
>
> Numbers refer to the **last listing of any kind**. Running something like
> `things tags` or `things areas` in between renumbers them, so `things done 1`
> would then point at a tag (the CLI refuses rather than changing it). When in
> doubt, list again just before a write.

## 1. Create the test area and project

- [ ] `things add-area CLI Test` prints `Created area 'CLI Test' (<uuid>)`, and
      the area appears in Things. *(AppleScript; macOS may ask to let your
      terminal control Things: allow it.)*
- [ ] `things areas`, note the number next to **CLI Test** (say `3`).
- [ ] `things add-project Test project --area-id 3 --todo One --todo Two`
      creates the project inside the area with two to-dos.
- [ ] `things todos --project "test project"` (the title, any case) lists One
      and Two; `things find --area "CLI Test"` lists them too.
- [ ] `things add First test -w today -c "Step A" -c "Step B" --list "Test project"`
      adds a to-do to Today, inside the project, with a two-item checklist.

## 2. CLI writes

Run `things today` first so the numbers below refer to its rows; find
**First test** in the list and use its number in place of `N`. After
`things schedule tomorrow N` it leaves Today, so if you list anything else in
between, take its number from `things upcoming` instead.

- [ ] `things done N`: ticked in Things; shows in `things logbook`.
- [ ] `things reopen N` (the number from `things logbook`): open again.
- [ ] `things schedule tomorrow N`: moves to Tomorrow in Things.
- [ ] `things deadline 2030-01-01 N`: deadline shows in Things.
- [ ] `things tag N --add <an existing tag>`: tag appears (Things ignores tags
      that don't exist yet).
- [ ] `things update N --title "First test, renamed" --append "Step C"`:
      title changes and the checklist gains Step C.
- [ ] `things update N --clear-checklist`: checklist emptied.
- [ ] `things cancel N`: shows as cancelled in the Logbook.
- [ ] Bulk: `things todos --project <Test project's number from things projects>`,
      then `things done 1 2`: both to-dos complete in one go.
- [ ] `things open today` brings Things to Today; `things open N` shows the item.

## 3. TUI

Start it with `things tui`. Add a to-do in **Test project** first (`n`), and
use that for the checks below.

- [ ] Layout: sidebar lists, projects and areas as in Things (areas with their
      projects underneath); `1`–`6` switch lists.
- [ ] `k` ticks the row straight away; Things shows it completed; `k` again reopens.
- [ ] `K` cancels.
- [ ] `t`, `e`, `r`, `o` move it to Today, This Evening, Anytime, Someday, matching Things.
- [ ] `]` / `[` move the start date by a day; `.` / `,` the deadline.
- [ ] `s` (When) and `D` (Deadline) prompt on the command line at the bottom;
      Enter applies, Escape cancels.
- [ ] `T` edits tags (pre-filled); clearing the line and pressing Enter removes them.
- [ ] `M` opens the Move list; type to filter, Enter moves it; Things agrees.
- [ ] `enter` renames.
- [ ] `i` shows details as a pop-up; `I` hides and shows the details pane.
- [ ] `f` finds; `O` jumps to a list by name; `L` shows an item's project.
- [ ] Edit something **in the Things app** while the TUI is open: the TUI
      refreshes on its own within a couple of seconds.

## 4. Assumptions to recheck

These rely on how Things stores data internally. All four were confirmed on a
Mac (Things 3, November 2026); recheck them after a Things update.

- [ ] **This Evening.** In Things, move a to-do to This Evening. It should
      appear under **This Evening** in both `things today` and the TUI. *(Read
      from the `startBucket` column; 1 is assumed to mean This Evening.)*
- [ ] **Duplicate.** In the TUI, select a to-do in Test project and press `d`.
      A copy should appear in Things. *(Uses the URL scheme's `duplicate=true`.)*
- [ ] **Reminders.** Give a to-do a reminder in Things; its details (`i`)
      should show `Reminder at HH:MM` with the right time.
- [ ] **Upcoming order.** `things upcoming` and the TUI's Upcoming should run
      soonest first, grouped by date, like Things.

## 5. MCP server still works

- [ ] In Claude (or another MCP client) using this checkout, ask "What's on
      my Today list?" The answer should match Things.

## 6. Clean up

- [ ] In Things, delete the **CLI Test** area (this deletes its project and
      to-dos too). Empty the Trash if you like. Or from the terminal, using
      the UUID `add-area` printed:
      `osascript -e 'tell application "Things3" to delete area id "<uuid>"'`
      (the area goes; its project and to-dos move to the Trash).

## Reporting problems

For anything that doesn't match, note the command or key, what Things showed,
and the output of `things show N --json` for the item involved.
