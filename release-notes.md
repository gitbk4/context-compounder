# v0.2.3: AI-discoverable wikis

compathy's wiki is no longer invisible to a fresh Claude Code session opening
the project. This release adds three breadcrumbs at scaffold time so any AI
agent finds and uses the wiki without having to be told.

Stdlib-only. No new dependencies. v1 scaffold flow unchanged; everything
below is additive.

## What's new

- **CLAUDE.md / README.md "Project context" sections.** At scaffold time,
  compathy writes (or merges into existing files) a sentinel-fenced section
  pointing at `context/wiki/index.md`, `schema.md`, and the wiki subdirs.
  Idempotent: re-running scaffold replaces the section in place; user
  content above and below the fence is preserved verbatim.
- **`compathy_query` MCP server.** A stdlib stdio MCP server that exposes
  five tools to any MCP-aware client: `compathy_index`,
  `compathy_get_page(slug)`, `compathy_search(query)`,
  `compathy_list_pages(page_type)`, `compathy_log_recent(n)`. Reuses
  `lint.py`'s flat-YAML parser. Also runs as a plain CLI for debugging.
- **Auto-registered `.mcp.json` at scaffold time.** Compathy now writes (or
  merges into existing) a project-local `.mcp.json` registering the
  compathy-wiki server, so Claude Code picks it up on first session without
  manual config. Other `mcpServers` entries are preserved.

## Compatibility

- Backwards-compatible with v0.2.x scaffolds. The new breadcrumbs are
  additive; existing projects gain them on next re-scaffold.
- Stdlib-only: requires Python 3.9+, no new packages.
- Graceful degradation: any breadcrumb failure logs to stderr and never
  aborts the scaffold.

## Known limits

- The MCP server uses line-delimited JSON over stdio. The strict MCP spec
  uses LSP-style `Content-Length` framing; Claude Code accepts both, but
  third-party MCP clients may not. Captured for a future tightening.
- `.mcp.json` paths are absolute at write time (not env-var-expanded), so
  moving a scaffolded project requires a re-scaffold or manual edit of the
  `--target` arg.
