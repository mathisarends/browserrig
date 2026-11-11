# Agent-facing tool documentation

- Keep each tool description concise: its purpose and any essential effect or
  limitation that changes when an agent should choose it.
- Describe non-obvious parameter semantics, units and selectors in the parameter's
  `Annotated[..., Field(description=...)]` metadata. Do not repeat them in the tool
  description, or restate defaults, enums and bounds already visible in the schema.
- Put shared workflows and cross-tool guidance in the relevant plugin's
  `instructions()` system prompt. For example, finding saved artifacts with
  `glob`/`grep`, reading bounded excerpts, pagination and interpreting extraction
  status belong to the file-tool instructions.
- Reuse shared guidance across alternative tool groups. Do not copy a workflow
  into every tool description or mention tools that the plugin does not provide.
- Preserve essential behavioral constraints while shortening descriptions. Avoid
  implementation details and exhaustive lists of examples or supported formats.
- When removing a tool parameter, update its schema, callers, presentation and
  documentation. Keep unrelated lower-level APIs unchanged unless needed.

See [docs/development.md](docs/development.md) for project checks and source conventions.
