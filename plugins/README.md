# Skitter Plugins

This directory is the default plugin root.

Each plugin should live in its own subdirectory and include a manifest named
`plugin.yaml`, `plugin.yml`, or `plugin.json`.

Example:

```text
plugins/
  honcho/
    plugin.yaml
    honcho_skitter_plugin.py
```

Plugins are loaded only when their manifest has `enabled: true`.

`example_plugin/` is a disabled-by-default reference plugin that registers all
non-memory hooks and logs their payload fields. Enable it locally when you want
to inspect hook timing or use it as a starting point for a new plugin.
