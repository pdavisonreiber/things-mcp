# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Development Setup
```bash
# Install dependencies (uses uv package manager)
uv sync

# Run the MCP server (stdio transport, default)
uv run things-mcp

# Run with HTTP transport
THINGS_MCP_TRANSPORT=http uv run things-mcp

# CLI and TUI (TUI needs the 'tui' extra: uv sync --extra tui)
uv run things --help
uv run things tui
```

### Testing

The project includes a comprehensive unit test suite covering URL scheme construction and data formatting functions.

```bash
# Install test dependencies (includes Textual for the TUI tests)
uv sync --extra test

# Run all tests
uv run pytest

# Run tests with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_url_scheme.py

# Run tests matching a pattern
uv run pytest -k "test_format"
```

Test coverage includes:
- All URL construction functions (add, update, show, search)
- Authentication token handling
- Data formatting for todos, projects, areas, and tags
- Error handling and edge cases
- Mock external dependencies (Things.py, shell commands)

## Architecture Overview

This is a Model Context Protocol (MCP) server that bridges Claude Desktop with the Things 3 task management app on macOS. The same package also ships a `things` CLI and a Textual TUI. All three front ends sit on one shared core:

0. **src/things_mcp/core.py** - Front-end-agnostic operations; put new logic here, not in a front end
   - Reads (list views, logbook/recent windows, search, tag usage) return plain lists of things.py dicts
   - Someday filtering and the `things.today()` workaround live here (server re-exports the old names)
   - Writes (`add_todo`, `update_todo`, `bulk_update_todos`, `update_items` for mixed to-dos/projects, areas, show/search in app)
   - User-facing problems raise `ThingsError`; each front end turns that into its own error output (MCP keeps the exact legacy strings)

1. **src/things_mcp/server.py** - MCP front end using FastMCP (3.x); tools are thin wrappers over `core`
   - Defines all MCP tools for interacting with Things (26 tools)
   - List views (inbox, today, upcoming, etc.)
   - CRUD operations for todos/projects/areas (Areas have create/read/update — no delete by design; see below)
   - Search and tag operations
   - Things URL scheme integration
   - Implements Someday project filtering to match Things UI behavior
   - **Pagination + structured responses**: the 16 list/search read tools accept optional `limit`/`offset` and return a FastMCP `ToolResult` carrying both a human-readable text channel and a `structured_content` envelope `{items, count, total, offset, limit}`. Two helpers drive this: `_paginate_format` (text) and `_paginate_result` (wraps text + JSON-safe structured data); `_error_result` wraps early-return/validation errors. `get_tag_usage` intentionally stays a plain string.

2. **src/things_mcp/url_scheme.py** - Things URL scheme + AppleScript implementation
   - Constructs Things URLs for various operations
   - Uses shell script with `open -g` to execute URLs without bringing Things to foreground
   - Handles authentication tokens for update operations
   - `add_area`/`update_area` use AppleScript (`osascript`) since the Things URL scheme has no area commands; all user-supplied strings are escaped (`\` then `"`) before being embedded in the AppleScript string literal to prevent injection, and `osascript` is invoked with an argv list (no shell)

3. **src/things_mcp/formatters.py** - Data formatting utilities
   - Converts Things database objects to human-readable text
   - Handles nested data (projects within areas, checklist items, etc.)

4. **src/things_mcp/cli.py** - `things` CLI (Click). Items are referenced by number from the last listing (cached in `$XDG_CACHE_HOME/things-mcp/last-list.json`), full UUID, or UUID prefix; `--project`/`--area` filters also take an exact title (`_resolve_named`). `--json` mirrors the MCP structured envelope.

5. **src/things_mcp/tui.py** - `things tui` / `things-tui` (Textual, optional `tui` extra). Mirrors the Things Mac app: sidebar order/nesting, list grouping (This Evening via `core.evening_uuids()`, which reads `TMTask.startBucket` because things.py doesn't), and key bindings taken from Things' Mac shortcuts with ⌘ dropped — keep new bindings consistent with that table in the README. Prompts use a persistent `CommandLine` above the key bar (one line idle; question on its own line above the input when asking) (`_ask` → `CommandLine.ask`; Enter submits, Escape cancels) and `?` opens a `HelpScreen` pop-up built from `KEY_HELP`. Writes are fire-and-forget, so it updates rows optimistically, re-reads after `REFRESH_AFTER_WRITE`, and polls the database file's mtime to pick up external changes.

   - **style.py** (shared with the CLI; must not import Textual) holds the Things-dark palette (`LIST_COLOURS`), icon sets (Unicode default; Nerd Font via `THINGS_TUI_ICONS=nerd`), the pixel-font `THINGS 3` sidebar logo, and the Rich renderers for rows, group headings, the list banner, sidebar entries and the detail card. Change the look there, not in tui.py or cli.py. The Textual theme (`THEME`) lives in tui.py.

6. **src/things_mcp/display.py** - List grouping shared by CLI and TUI (`group_today` with This Evening, `group_upcoming`, `group_by_location`, `group_logbook`, `group_by_heading`, `without_headings`) and `detail()` text. Rows use `project_title`/`area_title`/`heading_title` from things.py, so lists need no per-item lookups.

7. **tests/** - Test suite (286 tests; CI runs them on Python 3.12 and 3.13 via `.github/workflows/tests.yml`)
   - **conftest.py** - Pytest fixtures and mock data
   - **_helpers.py** - `tool_text()` reads the text channel from a `ToolResult` (or a plain-string result) so text assertions work across both return shapes
   - **test_url_scheme.py** - Tests for URL construction
   - **test_formatters.py** - Tests for data formatting
   - **test_things_server.py** - Tests for server tools (incl. pagination + structured-content shape)
   - **test_things_server_headings.py** - Tests for heading functionality
   - **test_someday_filtering.py** - Tests for Someday project filtering
   - **test_mcp_server_filtering.py** - Integration tests for MCP server filtering
   - **test_core.py**, **test_cli.py**, **test_tui.py** - Core helpers, CLI (Click `CliRunner`), TUI (Textual Pilot, headless)
   - **test_integration_db.py** - CLI, MCP tools and TUI against a synthetic Things database built by **fixtures/things_db.py** (real things.py queries; only `execute_url` is mocked)

## Key Implementation Details

- Uses things.py library for reading Things SQLite database
- Write operations use the Things URL scheme API, except Area create/update which use AppleScript (`osascript`)
- FastMCP (3.x) provides the MCP protocol implementation
- Read tools return a `ToolResult` (human-readable text + `structured_content`); write/report tools and error paths return plain strings
- Error handling for invalid UUIDs and missing parameters; pagination args validated by `_validate_pagination`
- Supports filtering and including nested items via parameters
- **Someday Project Filtering**: Tasks from Someday projects are filtered out of Today, Upcoming, and Anytime views to match the Things UI behavior and reduce clutter
- Unit tests mock all external dependencies (Things.py, shell commands)
- Pytest configuration in pyproject.toml with async support
- Supports both stdio (default) and HTTP transport modes

## Things URL Scheme Authentication

For update operations, the server automatically fetches and includes the auth-token from things.py. This allows updating existing items without user intervention.