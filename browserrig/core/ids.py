"""Names for the string IDs that key browser state, so a mapping says what it holds."""

type TargetId = str
"""A Chrome page target; one per tab."""

type DocumentId = str
"""One loaded document of a tab; a navigation starts a new one."""

type ActionId = str
"""One browser action, from its started event to its finished event."""
