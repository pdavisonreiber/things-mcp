from typing import List
import json
import logging
import os
import things  # noqa: F401 — tests patch things_mcp.server.things.*
from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult
from .formatters import format_todo, format_project, format_area, format_tag, format_heading
from . import core, url_scheme  # noqa: F401 — url_scheme kept importable from server
from .core import ThingsError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Transport configuration via environment variables
TRANSPORT = os.environ.get("THINGS_MCP_TRANSPORT", "stdio")  # "stdio" or "http"
HTTP_HOST = os.environ.get("THINGS_MCP_HOST", "127.0.0.1")
HTTP_PORT = int(os.environ.get("THINGS_MCP_PORT", "8000"))

# Initialize FastMCP server
mcp = FastMCP("Things")

# Shared logic lives in core; these names stay importable from server for
# backwards compatibility (tests and external callers use them).
_get_someday_context = core._get_someday_context
_is_in_someday_project = core._is_in_someday_project
_today_fallback = core._today_fallback
filter_someday_project_tasks = core.filter_someday_project_tasks
_parse_logbook_period = core.parse_period
_item_datetime = core.item_datetime


def _stop_datetime(todo):
    """Parse a todo's stop_date into a naive datetime, or None if absent/unparseable."""
    return core.item_datetime(todo, 'stop_date')


# Pagination helpers
def _validate_pagination(limit, offset):
    """Return an error string if limit/offset are invalid, else None."""
    if limit is not None and limit <= 0:
        return "Error: limit must be a positive integer"
    if offset < 0:
        return "Error: offset must be zero or a positive integer"
    return None


def _paginate_format(items, formatter, limit, offset, empty_msg, separator="\n\n---\n\n"):
    """Format a list with optional limit/offset pagination.

    When limit is None and offset is 0, output is byte-identical to the
    pre-pagination behavior (no header). Otherwise a "Showing X-Y of Z
    items" header is prepended so the caller knows there is more to fetch.
    """
    items = items or []
    total = len(items)

    # Fast path: preserve exact legacy output when no pagination requested.
    if limit is None and offset == 0:
        if not items:
            return empty_msg
        return separator.join(formatter(i) for i in items)

    if total == 0:
        return empty_msg
    if offset >= total:
        return f"Showing 0 of {total} items (offset {offset} is past the end)"

    end = total if limit is None else offset + limit
    page = items[offset:end]
    header = f"Showing {offset + 1}-{offset + len(page)} of {total} items\n\n"
    return header + separator.join(formatter(i) for i in page)


def _paginate_result(items, formatter, limit, offset, empty_msg, separator="\n\n---\n\n"):
    """Like _paginate_format, but returns a FastMCP ToolResult that carries
    BOTH the human-readable text (channel 1) AND JSON-safe structured data
    (channel 2) under structured_content.

    This is the pattern for opting a tool into structured output on FastMCP
    3.x while preserving the nicely formatted text. The text is identical to
    what _paginate_format produces; structured_content adds the raw item
    dicts plus pagination metadata so programmatic clients don't have to
    scrape the prose.
    """
    text = _paginate_format(items, formatter, limit, offset, empty_msg, separator)
    items = items or []
    total = len(items)
    end = total if limit is None else offset + limit
    page = [] if offset >= total else items[offset:end]
    # structured_content carries the same data the text renders — the full
    # item dicts (including nested checklist / sub-items). things.py dicts
    # contain datetime.date objects, which aren't JSON serializable, so coerce
    # the payload to JSON-safe primitives. Use `limit` to bound large lists;
    # it shrinks both channels together.
    safe_items = json.loads(json.dumps(page, default=str))
    structured = {
        "items": safe_items,
        "count": len(safe_items),
        "total": total,
        "offset": offset,
        "limit": limit,
    }
    return ToolResult(content=text, structured_content=structured)


def _error_result(msg):
    """ToolResult for an error / early-return path: human-readable text plus a
    structured {"error": msg} so structured-output clients see it too."""
    return ToolResult(content=msg, structured_content={"error": msg})


# List view tools
def _list_tool(fetch, formatter, limit, offset, empty_msg):
    """Shared body for the paginated read tools: validate pagination, fetch
    via core, and wrap the result (or a ThingsError) as a ToolResult."""
    err = _validate_pagination(limit, offset)
    if err:
        return _error_result(err)
    try:
        items = fetch()
    except ThingsError as e:
        return _error_result(str(e))
    return _paginate_result(items, formatter, limit, offset, empty_msg)


@mcp.tool
async def get_inbox(limit: int = None, offset: int = 0) -> ToolResult:
    """Get todos from Inbox

    Args:
        limit: Maximum number of items to return (default: all)
        offset: Number of items to skip from the start (default: 0)
    """
    return _list_tool(core.inbox, format_todo, limit, offset, "No items found")

@mcp.tool
async def get_today(limit: int = None, offset: int = 0) -> ToolResult:
    """Get todos due today

    Args:
        limit: Maximum number of items to return (default: all)
        offset: Number of items to skip from the start (default: 0)
    """
    # Someday-project tasks are filtered out before paginating.
    return _list_tool(core.today, format_todo, limit, offset, "No items found")

@mcp.tool
async def get_upcoming(limit: int = None, offset: int = 0) -> ToolResult:
    """Get upcoming todos

    Args:
        limit: Maximum number of items to return (default: all)
        offset: Number of items to skip from the start (default: 0)
    """
    return _list_tool(core.upcoming, format_todo, limit, offset, "No items found")

@mcp.tool
async def get_anytime(limit: int = None, offset: int = 0) -> ToolResult:
    """Get todos from Anytime list

    Args:
        limit: Maximum number of items to return (default: all)
        offset: Number of items to skip from the start (default: 0)
    """
    return _list_tool(core.anytime, format_todo, limit, offset, "No items found")

@mcp.tool
async def get_someday(limit: int = None, offset: int = 0) -> ToolResult:
    """Get todos from Someday list, including tasks in Someday projects

    Args:
        limit: Maximum number of items to return (default: all)
        offset: Number of items to skip from the start (default: 0)
    """
    return _list_tool(core.someday, format_todo, limit, offset, "No items found")

@mcp.tool
async def get_logbook(period: str = "7d", limit: int = 50, offset: int = 0,
                      project_uuid: str = None) -> ToolResult:
    """Get completed and canceled todos from Logbook, defaults to last 7 days, optionally filtered by project

    Args:
        period: Time period to look back (e.g., '3d', '1w', '2m', '1y'). Defaults to '7d'
        limit: Maximum number of entries to return. Defaults to 50
        offset: Number of entries to skip from the start (default: 0)
        project_uuid: Optional UUID of a project to filter by; includes items
            under the project's headings
    """
    return _list_tool(lambda: core.logbook(period, project_uuid), format_todo,
                      limit, offset, "No items found")

@mcp.tool
async def get_trash(limit: int = None, offset: int = 0) -> ToolResult:
    """Get trashed todos

    Args:
        limit: Maximum number of items to return (default: all)
        offset: Number of items to skip from the start (default: 0)
    """
    return _list_tool(core.trash, format_todo, limit, offset, "No items found")

# Basic operations
@mcp.tool
async def get_todos(project_uuid: str = None, include_items: bool = True,
                    limit: int = None, offset: int = 0) -> ToolResult:
    """Get todos from Things, optionally filtered by project

    Returns both human-readable text and structured JSON (the raw todo dicts
    plus pagination metadata) so MCP clients can consume either form.

    Args:
        project_uuid: Optional UUID of a specific project to get todos from
        include_items: Include checklist items
        limit: Maximum number of items to return (default: all)
        offset: Number of items to skip from the start (default: 0)
    """
    return _list_tool(lambda: core.todos(project_uuid, include_items), format_todo,
                      limit, offset, "No todos found")

@mcp.tool
async def get_projects(include_items: bool = False, limit: int = None, offset: int = 0) -> ToolResult:
    """Get all projects from Things

    Args:
        include_items: Include tasks within projects
        limit: Maximum number of items to return (default: all)
        offset: Number of items to skip from the start (default: 0)
    """
    return _list_tool(core.projects, lambda p: format_project(p, include_items),
                      limit, offset, "No projects found")

@mcp.tool
async def get_areas(include_items: bool = False, limit: int = None, offset: int = 0) -> ToolResult:
    """Get all areas from Things

    Args:
        include_items: Include projects and tasks within areas
        limit: Maximum number of items to return (default: all)
        offset: Number of items to skip from the start (default: 0)
    """
    return _list_tool(core.areas, lambda a: format_area(a, include_items),
                      limit, offset, "No areas found")

# Tag operations
@mcp.tool
async def get_tags(include_items: bool = False, limit: int = None, offset: int = 0) -> ToolResult:
    """Get all tags

    Args:
        include_items: Include items tagged with each tag
        limit: Maximum number of items to return (default: all)
        offset: Number of items to skip from the start (default: 0)
    """
    return _list_tool(core.tags, lambda t: format_tag(t, include_items),
                      limit, offset, "No tags found")

@mcp.tool
async def get_tagged_items(tag: str, limit: int = None, offset: int = 0) -> ToolResult:
    """Get items with a specific tag

    Args:
        tag: Tag title to filter by
        limit: Maximum number of items to return (default: all)
        offset: Number of items to skip from the start (default: 0)
    """
    return _list_tool(lambda: core.tagged_items(tag), format_todo, limit, offset,
                      f"No items found with tag '{tag}'")

@mcp.tool
async def get_tag_usage(only_unused: bool = False) -> str:
    """Report how many items use each tag, sorted by usage (highest first).

    Useful for cleaning up tags that accumulate over time. Identify
    rarely-used or unused tags first; then either remove them from any
    remaining items (via update_todo's tags parameter) or delete the
    tag manually in Things — the URL scheme does not support tag
    deletion or renaming.

    Args:
        only_unused: If true, return only tags with zero items.
    """
    tag_list = core.tags()
    if not tag_list:
        return "No tags found"
    rows = core.tag_usage(only_unused, tag_list=tag_list)
    if only_unused and not rows:
        return "No unused tags"
    return "\n".join(f"{name}: {open_c} open, {all_c} total" for name, open_c, all_c in rows)

@mcp.tool
async def get_headings(project_uuid: str = None, limit: int = None, offset: int = 0) -> ToolResult:
    """Get headings from Things

    Args:
        project_uuid: Optional UUID of a specific project to get headings from
        limit: Maximum number of items to return (default: all)
        offset: Number of items to skip from the start (default: 0)
    """
    return _list_tool(lambda: core.headings(project_uuid), format_heading,
                      limit, offset, "No headings found")

# Search operations
@mcp.tool
async def search_todos(query: str, limit: int = None, offset: int = 0) -> ToolResult:
    """Search todos by title or notes

    Args:
        query: Search term to look for in todo titles and notes
        limit: Maximum number of items to return (default: all)
        offset: Number of items to skip from the start (default: 0)
    """
    return _list_tool(lambda: core.search(query), format_todo, limit, offset,
                      f"No todos found matching '{query}'")

@mcp.tool
async def search_advanced(
    status: str = None,
    start_date: str = None,
    stop_date: str = None,
    deadline: str = None,
    tag: str = None,
    area: str = None,
    project: str = None,
    type: str = None,
    last: str = None,
    limit: int = None,
    offset: int = 0
) -> ToolResult:
    """Advanced todo search with multiple filters

    Args:
        status: Filter by todo status (incomplete, completed, canceled)
        start_date: Filter by start date (YYYY-MM-DD)
        stop_date: Filter by completion/cancellation date (YYYY-MM-DD with optional
            operator, e.g. '>=2024-01-01', or 'past'/'future')
        deadline: Filter by deadline (YYYY-MM-DD)
        tag: Filter by tag
        area: Filter by area UUID (includes to-dos in the area's projects)
        project: Filter by project UUID (includes items under the project's headings)
        type: Filter by item type (to-do, project, heading)
        last: Filter by creation date (e.g., '3d' for last 3 days, '1w' for last week, '1y' for last year)
        limit: Maximum number of items to return (default: all)
        offset: Number of items to skip from the start (default: 0)
    """
    return _list_tool(
        lambda: core.search_advanced(
            status=status, start_date=start_date, stop_date=stop_date,
            deadline=deadline, tag=tag, area=area, project=project, type=type,
            last=last,
        ),
        format_todo, limit, offset, "No matching todos found",
    )

# Recent items
@mcp.tool
async def get_recent(period: str, limit: int = None, offset: int = 0) -> ToolResult:
    """Get open (incomplete) items created within a rolling time window, newest first

    Args:
        period: How far back from now to look (e.g., '1d' = the last 24 hours, '1w', '2m', '1y')
        limit: Maximum number of items to return (default: all)
        offset: Number of items to skip from the start (default: 0)
    """
    return _list_tool(lambda: core.recent(period), format_todo, limit, offset,
                      f"No items found in the last {period}")

# Things URL Scheme tools
@mcp.tool
async def add_todo(
    title: str,
    notes: str = None,
    when: str = None,
    deadline: str = None,
    tags: List[str] = None,
    checklist_items: List[str] = None,
    list_id: str = None,
    list_title: str = None,
    heading: str = None,
    heading_id: str = None
) -> str:
    """Create a new todo in Things

    Args:
        title: Title of the todo
        notes: Notes for the todo
        when: When to schedule the todo (today, tomorrow, evening, anytime, someday, or YYYY-MM-DD).
            Use YYYY-MM-DD@HH:MM format to add a reminder (e.g., 2024-01-15@14:30)
        deadline: Deadline for the todo (YYYY-MM-DD)
        tags: Tags to apply to the todo
        checklist_items: Checklist items to add
        list_id: ID of project/area to add to
        list_title: Title of project/area to add to
        heading: Heading title to add under
        heading_id: Heading ID to add under (takes precedence over heading)
    """
    core.add_todo(
        title=title,
        notes=notes,
        when=when,
        deadline=deadline,
        tags=tags,
        checklist_items=checklist_items,
        list_id=list_id,
        list_title=list_title,
        heading=heading,
        heading_id=heading_id
    )
    return f"Created new todo: {title}"

@mcp.tool
async def add_area(title: str) -> str:
    """Create a new Area in Things 3

    Areas are top-level containers in Things 3 (e.g. "Work", "Personal", "Backlog").
    The Things URL scheme cannot create Areas, so this uses AppleScript.

    Args:
        title: Title of the area
    """
    area_id = core.add_area(title)
    return f"Created new area: {title} (id: {area_id})"

@mcp.tool
async def update_area(id: str, title: str = None, tags: List[str] = None) -> str:
    """Update an existing Area in Things 3 (rename and/or set tags)

    The Things URL scheme has no area operations, so this uses AppleScript.
    Only the fields you provide are changed.

    Note: there is no delete_area tool by design — deleting an Area in Things
    also deletes every project it contains, which is destructive and cannot be
    undone. Areas can be created, read, and updated here, but not deleted.

    Args:
        id: UUID of the area to update
        title: New name for the area
        tags: Tags to set on the area (replaces existing tags; only tags that
            already exist in Things are applied)
    """
    try:
        core.update_area(id, title=title, tags=tags)
    except ThingsError as e:
        return str(e)
    changed = []
    if title is not None:
        changed.append(f"title={title!r}")
    if tags is not None:
        changed.append(f"tags={tags}")
    return f"Updated area {id}: {', '.join(changed)}"

@mcp.tool
async def add_project(
    title: str,
    notes: str = None,
    when: str = None,
    deadline: str = None,
    tags: List[str] = None,
    area_id: str = None,
    area_title: str = None,
    todos: List[str] = None
) -> str:
    """Create a new project in Things

    Args:
        title: Title of the project
        notes: Notes for the project
        when: When to schedule the project (today, tomorrow, evening, anytime, someday, or YYYY-MM-DD).
            Use YYYY-MM-DD@HH:MM format to add a reminder (e.g., 2024-01-15@14:30)
        deadline: Deadline for the project (YYYY-MM-DD)
        tags: Tags to apply to the project
        area_id: ID of area to add to
        area_title: Title of area to add to
        todos: Initial todos to create in the project
    """
    core.add_project(
        title=title,
        notes=notes,
        when=when,
        deadline=deadline,
        tags=tags,
        area_id=area_id,
        area_title=area_title,
        todos=todos
    )
    return f"Created new project: {title}"

@mcp.tool
async def update_todo(
    id: str,
    title: str = None,
    notes: str = None,
    when: str = None,
    deadline: str = None,
    tags: List[str] = None,
    add_tags: List[str] = None,
    completed: bool = None,
    canceled: bool = None,
    list: str = None,
    list_id: str = None,
    heading: str = None,
    heading_id: str = None,
    checklist_items: List[str] = None,
    prepend_checklist_items: List[str] = None,
    append_checklist_items: List[str] = None,
) -> str:
    """Update an existing todo in Things

    Args:
        id: ID of the todo to update
        title: New title
        notes: New notes
        when: New schedule (today, tomorrow, evening, anytime, someday, or YYYY-MM-DD).
            Use YYYY-MM-DD@HH:MM format to add a reminder (e.g., 2024-01-15@14:30)
        deadline: New deadline (YYYY-MM-DD)
        tags: New tags (replaces all existing tags)
        add_tags: Tags to append without removing existing tags
        completed: Mark as completed
        canceled: Mark as canceled
        list: The title of a project or area to move the to-do into
        list_id: The ID of a project or area to move the to-do into (takes precedence over list)
        heading: The heading title to move the to-do under
        heading_id: The heading ID to move the to-do under (takes precedence over heading)
        checklist_items: Replace the entire checklist with these items. Pass an
            empty list to clear the checklist.
        prepend_checklist_items: Add these items to the start of the existing checklist
        append_checklist_items: Add these items to the end of the existing checklist
    """
    core.update_todo(
        id=id,
        title=title,
        notes=notes,
        when=when,
        deadline=deadline,
        tags=tags,
        add_tags=add_tags,
        completed=completed,
        canceled=canceled,
        list=list,
        list_id=list_id,
        heading=heading,
        heading_id=heading_id,
        checklist_items=checklist_items,
        prepend_checklist_items=prepend_checklist_items,
        append_checklist_items=append_checklist_items,
    )
    return f"Updated todo with ID: {id}"

@mcp.tool
async def bulk_update_todos(
    ids: List[str],
    list: str = None,
    list_id: str = None,
    tags: List[str] = None,
    add_tags: List[str] = None,
    when: str = None,
    deadline: str = None,
    heading: str = None,
    heading_id: str = None,
    completed: bool = None,
    canceled: bool = None,
) -> str:
    """Apply the same change to many to-dos in a single Things round-trip.

    Use for weekly-review style operations — e.g. "move every grocery item
    in my inbox to Shopping List", "tag this batch with 'next-quarter'",
    "complete all of these". One URL invocation replaces N sequential
    update_todo calls, which makes 20-task moves feel instant instead of
    taking minutes.

    All non-None parameters apply to every id in 'ids'. For per-item
    changes use update_todo individually.

    Args:
        ids: UUIDs of todos to update
        list: Project/area title to move all into
        list_id: Project/area UUID to move all into (takes precedence over list)
        tags: Replace tags on all (existing tags removed)
        add_tags: Append tags to all (existing tags preserved)
        when: Reschedule all (today, tomorrow, evening, anytime, someday, or YYYY-MM-DD)
        deadline: Set deadline on all (YYYY-MM-DD)
        heading: Move all under this heading title
        heading_id: Move all under this heading UUID (takes precedence over heading)
        completed: Mark all completed
        canceled: Mark all canceled
    """
    try:
        count = core.bulk_update_todos(
            ids, list=list, list_id=list_id, tags=tags, add_tags=add_tags,
            when=when, deadline=deadline, heading=heading, heading_id=heading_id,
            completed=completed, canceled=canceled,
        )
    except ThingsError as e:
        return str(e)
    return f"Submitted bulk update for {count} todos"

@mcp.tool
async def update_project(
    id: str,
    title: str = None,
    notes: str = None,
    when: str = None,
    deadline: str = None,
    tags: List[str] = None,
    completed: bool = None,
    canceled: bool = None
) -> str:
    """Update an existing project in Things

    Args:
        id: ID of the project to update
        title: New title
        notes: New notes
        when: New schedule (today, tomorrow, evening, anytime, someday, or YYYY-MM-DD).
            Use YYYY-MM-DD@HH:MM format to add a reminder (e.g., 2024-01-15@14:30)
        deadline: New deadline (YYYY-MM-DD)
        tags: New tags
        completed: Mark as completed
        canceled: Mark as canceled
    """
    core.update_project(
        id=id,
        title=title,
        notes=notes,
        when=when,
        deadline=deadline,
        tags=tags,
        completed=completed,
        canceled=canceled
    )
    return f"Updated project with ID: {id}"

@mcp.tool
async def show_item(
    id: str,
    query: str = None,
    filter_tags: List[str] = None
) -> str:
    """Show a specific item or list in Things

    Args:
        id: ID of item to show, or one of: inbox, today, upcoming, anytime, someday, logbook
        query: Optional query to filter by
        filter_tags: Optional tags to filter by
    """
    core.show_in_app(
        id=id,
        query=query,
        filter_tags=filter_tags
    )
    return f"Showing item: {id}"

@mcp.tool
async def search_items(query: str) -> str:
    """Search for items in Things

    Args:
        query: Search query
    """
    core.search_in_app(query)
    return f"Searching for '{query}'"


def main():
    """Main entry point for the Things MCP server."""
    if TRANSPORT == "http":
        mcp.run(transport="http", host=HTTP_HOST, port=HTTP_PORT)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
