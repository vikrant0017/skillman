# Skillman

Skillman is a terminal UI for [Vercel's `skills` CLI](https://github.com/vercel-labs/skills).

It builds the global-skills sidebar from `npx skills ls --json -g` and delegates
every mutation to `npx skills`. The CLI-provided path is used only when viewing a
selected skill's `SKILL.md`.

```bash
uv run skillman
```

Keys: `a` or `f` open the search-and-install dialog, `u` updates the selected
skill, `r` removes it after confirmation, `Ctrl+R` refreshes, and `Enter` views
its `SKILL.md`. The dialog queries the skills.sh API directly; after search,
press `Enter` on a result to install it. It stays open and reports the command
result until you choose Close.

Installing a result runs `npx skills add <source> --skill <skillId> --global --yes`.
