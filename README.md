# Things MCP Server

This [Model Context Protocol (MCP)](https://modelcontextprotocol.io/introduction) server lets you use ChatGPT, Codex, Claude Desktop, and other MCP clients to interact with your task management data in [Things 3](https://culturedcode.com/things) from Cultured Code. You can ask your assistant to create tasks, analyze projects, help manage priorities, and more.

This server leverages the [Things.py](https://github.com/thingsapi/things.py) library and the [Things URL Scheme](https://culturedcode.com/things/help/url-scheme/). 

## Support the Project

If you find this project helpful, consider supporting its development:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/haldick)

## Features

- Access to all major Things lists (Inbox, Today, Upcoming, etc.)
- Project and area management
- Tag operations
- Advanced search capabilities
- Recent items
- Detailed item information including checklists
- Support for nested data (projects within areas, todos within projects)
- Someday project filtering: tasks in Someday projects are automatically excluded from Today, Upcoming, and Anytime views, matching Things UI behavior


## Installation

### Prerequisites
- macOS (Things 3 is Mac-only)
- Things 3 app with "Enable Things URLs" turned on (Settings → General)
- An MCP client, such as the ChatGPT desktop app, Codex, Claude Desktop, or Claude Code
- [uv](https://docs.astral.sh/uv/) Python package manager: `brew install uv`

### Install via uvx (Any MCP Client)

Things MCP is published on PyPI and can be run directly with `uvx`:

```bash
uvx things-mcp
```

Configure your MCP client to use `uvx` with `things-mcp` as the argument.

### Claude Desktop

#### Option 1: One-Click Install (Recommended)

1. Download the latest file from the [releases page](https://github.com/hald/things-mcp/releases)
2. Double-click the `.mcpb` file
3. Done!

#### Option 2: Manual Config

1. Go to **Claude → Settings → Developer → Edit Config**
2. Add the Things server:

```json
{
  "mcpServers": {
    "things": {
      "command": "uvx",
      "args": ["things-mcp"]
    }
  }
}
```

3. Save and restart Claude Desktop

### Claude Code

```bash
claude mcp add-json things '{"command":"uvx","args":["things-mcp"]}'
```

To make it available globally (across all projects), add `-s user`:
```bash
claude mcp add-json -s user things '{"command":"uvx","args":["things-mcp"]}'
```

### ChatGPT Desktop and Codex

The ChatGPT desktop app, Codex CLI, and Codex IDE extension share the same local MCP configuration. The quickest way to add Things MCP is with the Codex CLI:

```bash
codex mcp add things -- uvx things-mcp
```

Confirm that the server is configured:

```bash
codex mcp list
```

You can also configure it in the ChatGPT desktop app:

1. Open **Settings → MCP servers**
2. Select **Add server**
3. Enter `things` as the name, choose **STDIO**, and enter the result of `which uvx` as the command to launch (should look similar to /opt/homebrew/bin/uvx)
4. Enter `things-mcp` under arguments
5. Save the server and select **Restart**

> [!IMPORTANT]
> When using the ChatGPT desktop client, you must use **Work** mode to access Things MCP. Select **ChatGPT** from the top-left menu, then choose **Work** from the toggle at the top of the page. Regular **Chat** mode does not use locally configured MCP tools. You can also select the separate **Codex** view, which shares the same MCP configuration.

In ChatGPT Work or Codex, type `/mcp` to check that the Things server is connected, then try asking, "What's in my Things inbox?"

This local setup does not work in ChatGPT on the web because the web client does not read local Codex MCP configuration. See [OpenAI's MCP documentation](https://developers.openai.com/codex/mcp/) and [ChatGPT Work and Codex](https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex) for current availability and interface details.

### Verify it's working

After installation:
- If using Claude Desktop, you should see "Things MCP" in the "Search and tools" list
- If using ChatGPT Work or Codex, type `/mcp` and confirm that the Things server is connected
- Try asking: "What's in my Things inbox?"

### Sample Usage with Claude Desktop
* "What's on my todo list today?"
* "Create a todo to pack for my beach vacation next week, include a packing checklist."
* "Evaluate my current todos using the Eisenhower matrix."
* "Help me conduct a GTD-style weekly review using Things."
* "Show me tasks that haven't been modified in over a month."

#### Tips
* Create a project in Claude with custom instructions that explains how you use Things and organize areas, projects, tags, etc. Tell Claude what information you want included when it creates a new task (eg asking it to include relevant details in the task description might be helpful).
* Try adding another MCP server that gives Claude access to your calendar. This will let you ask Claude to block time on your calendar for specific tasks, create todos from upcoming calendar events (eg prep for a meeting), etc.
* Use task ages to identify stale items: "Which tasks in my Anytime list are older than 2 weeks?"


## Command Line and Terminal UI

The same package also installs a `things` command-line tool and a full-screen terminal interface. They share the MCP server's code, so they see the same lists (including the Someday-project filtering and Logbook fixes) and write through the same Things URL scheme and AppleScript.

### Install

```bash
# Installs things (CLI), things-tui and things-mcp
uv tool install "things-mcp @ git+https://github.com/pdavisonreiber/things-mcp"

# From a checkout
uv sync && uv run things
```

Like the MCP server, it runs on the Mac where Things 3 is installed and needs "Enable Things URLs" turned on for writes.

### CLI

```bash
things                      # Today (same as: things today)
things inbox                # also: upcoming, anytime, someday, trash
things logbook -p 2w        # completed and canceled in the last 2 weeks
things recent 3d            # open items created in the last 3 days
things projects             # also: areas, tags, headings, todos --project 2
things search dentist       # title/notes search; `things find` takes filters
things show 3               # full details of item 3 from the last listing

things add Buy oat milk -w today -t errand -c "Check fridge first"
things add Draft agenda --in 2 --heading "Prep"
things done 1 3             # complete items 1 and 3 from the last listing
things schedule tomorrow 2  # also: deadline, move --to, tag --add, cancel, reopen
things update 4 --title "New title" --notes "…" --append "Checklist item"
things open today           # reveal a list or item in the Things app
```

- **Referring to items:** use the number shown next to an item in the most recent listing, a full UUID, or a unique UUID prefix (at least 4 characters). Numbers are remembered in `~/.cache/things-mcp/last-list.json`.
- **Output:** one line per item by default, in the same style as the TUI (grouped like the Things list, with colours in a terminal and plain text when piped); `--long` / `-l` prints full details; `--json` prints the same `{items, count, total, offset, limit}` envelope as the MCP tools' structured output. Listing commands take `--limit` / `-n` and `--offset`.
- **Several items at once:** `done`, `cancel`, `schedule`, `deadline`, `move` and `tag` accept several items. Multiple to-dos go to Things in one bulk call (this needs the URL-scheme auth token, which is read from the Things database automatically).
- Run `things --help` or `things <command> --help` for every option.

### TUI

```bash
things tui      # or: things-tui
```

The layout follows the Things Mac app: the sidebar is grouped the same way (Inbox / Today, Upcoming, Anytime, Someday / Logbook, Trash / projects / areas with their projects nested beneath), Today ends with a **This Evening** section, Upcoming and the Logbook are grouped by date, Anytime and Someday by project, and projects by heading. A detail pane stands in for Things' inline to-do card.

It has a flat layout (no boxes or panels; the sidebar is a slightly lighter shade, and there's a persistent command line above the key bar where prompts ask for input) and a dark palette modelled on Things' dark mode: each built-in list has its own icon colour, deadlines show as red flags with days left, and tags show as #tags. A retro touch: the sidebar opens with a pixel-font `THINGS 3` logo in amber. Icons are plain Unicode by default. If your terminal uses a [Nerd Font](https://www.nerdfonts.com), set `THINGS_TUI_ICONS=nerd` for proper glyphs.

Keys follow [Things' Mac shortcuts](https://culturedcode.com/things/support/articles/2785159/) with ⌘ dropped and ⇧ kept. ⌃ and ⌥ are dropped too, because terminals can't send them reliably (⌃[ is the same as Escape, and ⌥ types special characters on macOS). Press `?` in the app for the full list.

| Key | Action | Things |
|---|---|---|
| `n` / `space` | New to-do in the current list | ⌘N / Space |
| `enter` | Open: enter a project or area, or edit a to-do's title | Return |
| `k` / `K` | Complete (again to reopen) / cancel | ⌘K / ⌥⌘K |
| `d` | Duplicate | ⌘D |
| `M` | Move: pick a project or area from a list | ⇧⌘M |
| `s` | When… | ⌘S |
| `t` `e` `r` `o` | Start Today / This Evening / Anytime / Someday | ⌘T ⌘E ⌘R ⌘O |
| `]` `[` (`}` `{`) | Start date +/- 1 day (1 week) | ⌃] ⌃[ (⌃⇧] ⌃⇧[) |
| `D` | Deadline | ⇧⌘D |
| `.` `,` (`>` `<`) | Deadline +/- 1 day (1 week) | ⌃. ⌃, (⌃⇧. ⌃⇧,) |
| `T` | Edit tags | ⇧⌘T |
| `1`–`6` | Inbox, Today, Upcoming, Anytime, Someday, Logbook | ⌘1–⌘6 |
| `f` | Find | ⌘F |
| `O` | Go to a list, project or area by name | ⇧⌘O / Type Travel |
| `L` | Show in parent list | ⌘L |
| `left` / `right` | Back / enter project | ⌘← / ⌘→ |
| `alt+up` / `alt+down` | Select first / last | ⌥↑ / ⌥↓ |
| `/` | Show/hide sidebar | ⌘/ |
| `i` / `I` | Details pop-up / show or hide the details pane | — |
| `ctrl+o` | Show the item in the Things app | — |
| `ctrl+r` | Refresh | — |
| `?` | Key help (pop-up) | — |
| `q` | Quit | ⌘Q |

Not available, because neither the URL scheme nor things.py supports them: reordering (⌘↑/↓), repeat schedules (⇧⌘R), new headings (⇧⌘N), moving completed items to the Logbook (⇧⌘Y) and tag filtering (⌃⌥ + tag shortcut). Unlike Things, typing letters doesn't start a search, because single letters are commands here; use `f` or `O`.

### How writes behave

Most writes go through the Things URL scheme, which doesn't report back: the command returns once macOS has handed the URL to Things, not once Things has saved it. The CLI says "sent to Things" for that reason, and a listing run straight afterwards may not show the change yet. The TUI updates the changed row immediately, re-reads the database a second later, and also refreshes whenever Things writes to its database, so changes made in the Things app appear too.


## Available Tools

### List Views
- `get-inbox` - Get todos from Inbox
- `get-today` - Get todos due today
- `get-upcoming` - Get upcoming todos
- `get-anytime` - Get todos from Anytime list
- `get-someday` - Get todos from Someday list, including tasks in Someday projects
- `get-logbook` - Get completed and canceled todos, optionally for one project
- `get-trash` - Get trashed todos

### Basic Operations
- `get-todos` - Get todos, optionally filtered by project
- `get-projects` - Get all projects
- `get-areas` - Get all areas

### Tag Operations
- `get-tags` - Get all tags
- `get-tagged-items` - Get items with a specific tag
- `get-tag-usage` - Report how many items use each tag, sorted by usage; flag unused tags for cleanup

### Search Operations
- `search-todos` - Simple search by title/notes
- `search-advanced` - Advanced search with multiple filters

### Time-based Operations
- `get-recent` - Get open items created within a rolling time window

### Things URL Scheme Operations
- `add-todo` - Create a new todo
- `add-project` - Create a new project
- `add-area` - Create a new Area (via AppleScript; Things URL scheme has no add-area command)
- `update-area` - Update an existing Area: rename or set tags (via AppleScript)
- `update-todo` - Update an existing todo
- `bulk-update-todos` - Apply the same update to many todos in a single operation
- `update-project` - Update an existing project
- `show-item` - Show a specific item or list in Things
- `search-items` - Search for items in Things

## Tool Parameters

### Pagination (most read tools)
The list/search read tools (`get-inbox`, `get-today`, `get-upcoming`, `get-anytime`, `get-someday`, `get-logbook`, `get-trash`, `get-todos`, `get-projects`, `get-areas`, `get-tags`, `get-tagged-items`, `get-headings`, `search-todos`, `search-advanced`, `get-recent`) accept optional pagination:
- `limit` - Maximum number of items to return (default: all; `get-logbook` defaults to 50)
- `offset` - Number of items to skip from the start (default: 0)

When neither is set, output is unchanged. When set, a `Showing X-Y of Z items` header is prepended so you know how much more there is. An `offset` past the end is reported distinctly from an empty result.

These same read tools also return **structured content** alongside the human-readable text: MCP clients receive the raw item dicts plus `count`/`total`/`offset`/`limit` under `structured_content`, so data can be consumed programmatically without parsing the formatted text.

### get-todos
- `project_uuid` (optional) - Filter todos by project
- `include_items` (optional, default: true) - Include checklist items

### get-projects / get-areas / get-tags
- `include_items` (optional, default: false) - Include contained items

### search-advanced
- `status` - Filter by status (incomplete/completed/canceled)
- `start_date` - Filter by start date (YYYY-MM-DD)
- `deadline` - Filter by deadline (YYYY-MM-DD)
- `tag` - Filter by tag
- `area` - Filter by area UUID
- `stop_date` - Filter by completion/cancellation date (YYYY-MM-DD, optionally with an operator such as '>=2024-01-01', or 'past'/'future')
- `project` - Filter by project UUID (includes items under the project's headings)
- `type` - Filter by item type (to-do/project/heading)
- `last` - Filter by creation date (e.g., '3d' for last 3 days, '1w' for last week)

### get-recent
- `period` (required) - Rolling window back from now (e.g., '1d' = the last 24 hours, '1w', '2m', '1y'); months ≈ 30 days, years ≈ 365 days. Returns open (incomplete) items only, newest first

### get-logbook
- `period` (optional, default: '7d') - Look-back window by completion date. Accepts `d`/`w`/`m`/`y` (e.g., '3d', '1w', '2m', '1y'); months ≈ 30 days, years ≈ 365 days
- `limit` (optional, default: 50) - Maximum number of items to return
- `project_uuid` (optional) - Only return items from this project, including items under its headings

Returns both completed and canceled items; each item's `status` tells them apart.

### get-tag-usage
- `only_unused` (optional, default: false) - Return only tags that no item references (cleanup candidates)

### update-todo (checklist & tags)
- `tags` - Replace all tags on the todo
- `add_tags` - Append tags without removing existing ones
- `checklist_items` - Replace the entire checklist with this list; pass an empty list (`[]`) to clear it. Omit it to leave the checklist unchanged
- `prepend_checklist_items` - Add these items to the top of the checklist
- `append_checklist_items` - Add these items to the bottom of the checklist

### bulk-update-todos
Applies the same change to every todo in `ids` in a single operation. Requires the Things auth token to be enabled (Things → Settings → General → Enable Things URLs → Manage); the server reads it automatically.
- `ids` (required) - List of todo UUIDs to update
- `list` / `list_id` - Move all into a project/area (by title or UUID)
- `tags` / `add_tags` - Replace or append tags on all
- `when` - Reschedule all (keyword or YYYY-MM-DD)
- `deadline` - Set deadline on all (YYYY-MM-DD)
- `heading` / `heading_id` - Move all under a heading (by title or UUID)
- `completed` / `canceled` - Mark all completed or canceled

### Scheduling with Reminders (add-todo, add-project, update-todo, update-project)
- `when` - Accepts multiple formats:
  - Keywords: `today`, `tomorrow`, `evening`, `anytime`, `someday`
  - Date: `YYYY-MM-DD` (e.g., `2024-01-15`)
  - DateTime with reminder: `YYYY-MM-DD@HH:MM` (e.g., `2024-01-15@14:30`)

## Troubleshooting

If it's not working:

1. **Make sure Things 3 is installed and has been opened at least once**
   - The Things database needs to exist for the server to work

2. **Check that "Enable Things URLs" is turned on**
   - Open Things → Settings → General → Enable Things URLs

3. **Claude Desktop can't find `uvx`**
   - Install uv globally with Homebrew (`brew install uv`) 
   - **Alternative**: Use the full path to `uvx` in your config. Find it with `which uvx` (typically `/Users/USERNAME/.local/bin/uvx`)

## Development

### Running Tests

The project includes a comprehensive unit test suite for the URL scheme and formatter modules.

```bash
# Install test dependencies (includes Textual for the TUI tests)
uv sync --extra test

# Run all tests
uv run pytest

# Run tests with verbose output
uv run pytest -v

# Run a specific test file
uv run pytest tests/test_url_scheme.py

# Run tests matching a pattern
uv run pytest -k "test_add_todo"
```

### CLI and TUI Test Plan

[`docs/cli_tui_test_plan.md`](docs/cli_tui_test_plan.md) is a short checklist for trying the CLI and TUI against real Things on a Mac. The automated tests run on Linux with Things mocked out, and run on every push via GitHub Actions.

### MCP Integration Test

The project includes an integration test plan that can be executed by Claude (via Claude Cowork or Claude Code) to verify all MCP tools work correctly against a live Things database.

See [`docs/mcp_integration_test_plan.md`](docs/mcp_integration_test_plan.md) for the full test plan.

### Project Structure

```
things-mcp/
├── src/things_mcp/      # Main package
│   ├── __init__.py      # Package exports
│   ├── __main__.py      # Entry point for python -m
│   ├── core.py          # Shared reads/writes used by every front end
│   ├── server.py        # MCP server implementation
│   ├── cli.py           # `things` command-line interface
│   ├── tui.py           # `things tui` terminal interface (Textual)
│   ├── style.py         # Palette, icons and row/detail rendering (CLI and TUI)
│   ├── display.py       # List grouping and detail text (CLI and TUI)
│   ├── url_scheme.py    # Things URL scheme + AppleScript implementation
│   └── formatters.py    # Data formatting utilities
├── tests/               # Unit tests
│   ├── conftest.py      # Test fixtures and configuration
│   ├── test_url_scheme.py
│   ├── test_formatters.py
│   ├── test_someday_filtering.py
│   ├── test_mcp_server_filtering.py
│   ├── test_core.py, test_cli.py, test_tui.py
│   ├── test_integration_db.py  # CLI/MCP/TUI against a synthetic Things database
│   └── fixtures/things_db.py   # Builds that database
├── docs/                # Documentation
│   └── mcp_integration_test_plan.md  # Claude-executable integration test
├── manifest.json        # MCPB package manifest
├── build_mcpb.sh        # MCPB package build script
├── pyproject.toml       # Project dependencies, build config, and pytest config
├── .env.example         # Sample environment configuration
└── run.sh               # Convenience runner script
```

### HTTP Transport

By default, the server uses stdio transport for communication with MCP clients. For remote access scenarios, you can run the server with HTTP transport.

#### Configuration

Set these environment variables to enable HTTP transport:

| Variable | Default | Description |
|----------|---------|-------------|
| `THINGS_MCP_TRANSPORT` | `stdio` | Transport type: `stdio` or `http` |
| `THINGS_MCP_HOST` | `127.0.0.1` | HTTP server bind address |
| `THINGS_MCP_PORT` | `8000` | HTTP server port |

#### Example

```bash
# Using uvx
THINGS_MCP_TRANSPORT=http THINGS_MCP_HOST=0.0.0.0 THINGS_MCP_PORT=8000 uvx things-mcp

# Or from source
THINGS_MCP_TRANSPORT=http THINGS_MCP_HOST=0.0.0.0 THINGS_MCP_PORT=8000 uv run things-mcp
```

See `.env.example` for a sample configuration file.
