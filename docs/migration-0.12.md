# Migrate from 0.11.x to 0.12.0

[Migration guides](migrations.md) · [Release notes](../CHANGELOG.md#0120-2026-11-21)

## Upgrade Harnessed

BrowserRig 0.12 pins Harnessed and its provider, MCP and OpenTelemetry extras to
0.25.0. To carry over session stores from BrowserRig 0.11, export the
conversations and import them into a fresh store using the
[Harnessed 0.23 migration steps](agent-guide.md#migrating-from-harnessed-023).
Stores already on Harnessed 0.24 can be reopened directly.

In custom compositions, pass the existing timeout values to
`AgentLoop(tool_timeout_seconds=...)`, `Approvals(timeout_seconds=...)` and
`MCP(startup_timeout_seconds=..., call_timeout_seconds=...)`. See the
[Harnessed upgrade notes](agent-guide.md#upgrading-from-harnessed-024) for
changes that affect custom extensions.

## Update drag tools and cursor routes

If your application chooses its browser tools explicitly, add
`PointerDragTools()` for `drag_at` and `ReferenceDragTools()` for `drag`.
The standard `Agent` includes both. Pass only the endpoints to these tools.
The input motor sets the timing. Direct Python callers can still pass
`duration_seconds` to `Input.mouse.drag()`.

Rename `Motor.pointer_route()` to `Motor.cursor_route()`,
`InputPacing(pointer_route=...)` to `InputPacing(cursor_route=...)` and
`PointerRoutePlanner` to `CursorRoutePlanner`. The same planner now handles
free cursor moves and moves with the primary button held during a drag.
