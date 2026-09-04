"""A Textual frontend for Vercel's ``skills`` command-line tool."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlencode
from urllib.request import urlopen

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Collapsible,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    MarkdownViewer,
    Static,
)

FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path
    target: Path | None


@dataclass(frozen=True)
class SearchSkill:
    """A skill returned by the skills.sh search API."""

    id: str
    skill_id: str
    name: str
    installs: int
    source: str


def frontmatter_value(text: str, key: str) -> str:
    """Return a scalar YAML-frontmatter value without requiring PyYAML."""
    match = FRONTMATTER.match(text)
    if not match:
        return ""
    value = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", match.group(1))
    return value.group(1).strip().strip("\"'") if value else ""


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return a concise metadata display and Markdown body without YAML frontmatter."""
    match = FRONTMATTER.match(text)
    if not match:
        return "No frontmatter metadata.", text
    fields: list[str] = []
    for line in match.group(1).splitlines():
        if line and not line[0].isspace() and ":" in line:
            key, value = line.split(":", 1)
            fields.append(
                f"{key.strip()}: {value.strip().strip(chr(34)).strip(chr(39)) or '…'}"
            )
    return "\n".join(fields) or "No frontmatter metadata.", text[match.end() :].lstrip()


class SearchInput(Input):
    """Inputs whose first Escape leaves typing mode instead of closing a modal."""

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self.blur()


def skills_from_cli_json(payload: str) -> list[Skill]:
    """Convert ``npx skills ls --json -g`` output to sidebar records."""
    rows = json.loads(payload)
    if not isinstance(rows, list):
        raise TypeError("The skills CLI did not return a JSON array.")
    found: list[Skill] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("name") or not row.get("path"):
            continue
        cli_path = Path(str(row["path"])).expanduser()
        skill_file = cli_path if cli_path.name == "SKILL.md" else cli_path / "SKILL.md"
        skill_dir = skill_file.parent
        found.append(
            Skill(
                str(row["name"]),
                str(row.get("description") or "No description provided."),
                skill_dir,
                skill_dir.resolve() if skill_dir.is_symlink() else None,
            )
        )
    return sorted(found, key=lambda skill: skill.name.casefold())


def load_global_skills() -> list[Skill]:
    """Ask Vercel's CLI for the authoritative global skill list."""
    result = subprocess.run(
        ["npx", "skills", "ls", "--json", "-g"],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "npx skills ls failed")
    return skills_from_cli_json(result.stdout)


def search_skills_api(query: str) -> list[SearchSkill]:
    """Search skills.sh directly, without starting the interactive CLI finder."""
    url = f"https://skills.sh/api/search?{urlencode({'q': query, 'limit': '10'})}"
    with urlopen(url, timeout=15) as response:
        payload = json.load(response)
    rows = payload.get("skills", []) if isinstance(payload, dict) else []
    return [
        SearchSkill(
            id=str(row["id"]),
            skill_id=str(row["skillId"]),
            name=str(row["name"]),
            installs=int(row.get("installs", 0)),
            source=str(row["source"]),
        )
        for row in rows
        if isinstance(row, dict)
        and all(row.get(key) for key in ("id", "skillId", "name", "source"))
    ]


def install_global_skill(skill: SearchSkill) -> int:
    """Install one API search result using Vercel's non-interactive CLI form."""
    command = [
        "npx",
        "skills",
        "add",
        skill.source,
        "--skill",
        skill.skill_id,
        "--global",
        "--yes",
    ]
    result = subprocess.run(
        command, text=True, capture_output=True, timeout=180, check=False
    )
    return result.returncode


class SkillItem(ListItem):
    def __init__(self, skill: Skill) -> None:
        super().__init__(Label(skill.name))
        self.skill = skill


class SearchItem(ListItem):
    def __init__(self, skill: SearchSkill) -> None:
        super().__init__(
            Label(f"{skill.name}  ·  {skill.source}  ·  {skill.installs:,} installs")
        )
        self.skill = skill


class SearchInstallScreen(ModalScreen[None]):
    """Search skills.sh and install highlighted results without closing the modal."""

    CSS = """
    SearchInstallScreen { align: center middle; }
    #search-dialog { width: 110; height: 32; padding: 1 2; background: $surface; border: heavy $primary; }
    #search-results { height: 1fr; margin-top: 1; border: round $secondary; }
    #search-status { height: auto; min-height: 3; margin-top: 1; color: $text-muted; }
    #search-actions { height: 3; align: right middle; }
    #search-actions Button { margin-left: 1; }
    """
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("slash", "focus_query", "Search"),
        ("escape", "close", "Close"),
    ]

    def __init__(
        self,
        searcher: Callable[[str], list[SearchSkill]] = search_skills_api,
        installer: Callable[[SearchSkill], int] = install_global_skill,
        refresh_catalog: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.searcher = searcher
        self.installer = installer
        self.refresh_catalog_callback = refresh_catalog

    def compose(self) -> ComposeResult:
        with Vertical(id="search-dialog"):
            yield Label("Search and install skills")
            yield SearchInput(placeholder="Search skills…", id="query")
            yield ListView(id="search-results")
            yield Static("Type a query and press Enter to search.", id="search-status")
            with Horizontal(id="search-actions"):
                yield Button("Close", id="close")
                yield Button("Search", variant="primary", id="search")

    def on_mount(self) -> None:
        self.query_one("#query", Input).focus()

    def action_focus_query(self) -> None:
        self.query_one("#query", Input).focus()

    def action_cursor_down(self) -> None:
        view = self.query_one("#search-results", ListView)
        view.focus()
        view.action_cursor_down()

    def action_cursor_up(self) -> None:
        view = self.query_one("#search-results", ListView)
        view.focus()
        view.action_cursor_up()

    def action_close(self) -> None:
        self.dismiss()

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss()
        elif event.button.id == "search":
            self.search()

    @on(Input.Submitted, "#query")
    def submit_query(self) -> None:
        self.search()

    @on(ListView.Selected, "#search-results")
    def install_highlighted(self, event: ListView.Selected) -> None:
        if isinstance(event.item, SearchItem):
            self.install(event.item.skill)

    def search(self) -> None:
        query = self.query_one("#query", Input).value.strip()
        if not query:
            self.query_one("#search-status", Static).update(
                "Enter a search term first."
            )
            return
        self.search_api(query)

    @work(thread=True, exclusive=True)
    def search_api(self, query: str) -> None:
        self.app.call_from_thread(self.set_status, f"Searching for '{query}'…")
        try:
            results = self.searcher(query)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self.app.call_from_thread(self.show_search_error, str(error))
            return
        self.app.call_from_thread(self.show_results, results)

    def set_status(self, message: str) -> None:
        self.query_one("#search-status", Static).update(message)

    def show_search_error(self, error: str) -> None:
        self.query_one("#search-status", Static).update(f"Search failed: {error}")

    def show_results(self, results: list[SearchSkill]) -> None:
        view = self.query_one("#search-results", ListView)
        view.clear()
        view.extend(SearchItem(skill) for skill in results)
        if results:
            view.index = 0
            view.focus()
            self.query_one("#search-status", Static).update(
                "Return installs the highlighted skill. The dialog stays open."
            )
        else:
            self.query_one("#search-status", Static).update(
                "No skills found. Try a broader search."
            )

    def install(self, skill: SearchSkill) -> None:
        self.install_api_skill(skill)

    @work(thread=True, exclusive=True)
    def install_api_skill(self, skill: SearchSkill) -> None:
        self.app.call_from_thread(self.set_status, f"Installing {skill.name}…")
        try:
            code = self.installer(skill)
        except (OSError, subprocess.TimeoutExpired) as error:
            self.app.call_from_thread(self.show_install_error, skill, str(error))
            return
        self.app.call_from_thread(self.show_install_result, skill, code)

    def show_install_result(self, skill: SearchSkill, code: int) -> None:
        if code == 0:
            self.set_status(
                f"Installed {skill.name} globally (exit code 0). You can close this dialog or install another skill."
            )
            if self.refresh_catalog_callback is not None:
                self.refresh_catalog_callback()
            elif isinstance(self.app, SkillsManager):
                self.app.refresh_catalog()
        else:
            self.set_status(
                f"Could not install {skill.name} (exit code {code}). "
                "Check that the source is reachable, then try again."
            )

    def show_install_error(self, skill: SearchSkill, error: str) -> None:
        self.set_status(f"Could not start installing {skill.name}: {error}")


class ConfirmRemove(ModalScreen[bool]):
    CSS = """
    ConfirmRemove { align: center middle; }
    #remove-dialog { width: 62; height: auto; padding: 1 2; background: $surface; border: heavy $error; }
    #remove-actions { height: 3; margin-top: 1; align: right middle; }
    #remove-actions Button { margin-left: 1; }
    """
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "cancel", "Cancel")]

    def __init__(self, skill_name: str) -> None:
        super().__init__()
        self.skill_name = skill_name

    def compose(self) -> ComposeResult:
        with Vertical(id="remove-dialog"):
            yield Label(f"Remove '{self.skill_name}' from global agent skills?")
            yield Label("This delegates deletion to `npx skills remove`.")
            with Horizontal(id="remove-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Remove", variant="error", id="remove")

    @on(Button.Pressed)
    def answer(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "remove")

    def action_cancel(self) -> None:
        self.dismiss(False)


class SkillsManager(App[None]):
    TITLE = "Skillman"
    SUB_TITLE = "Shared agent skills"
    CSS = """
    #catalog { width: 25%; min-width: 22; height: 1fr; border: round $primary; padding: 0; }
    #catalog > Contents { height: 1fr; }
    #catalog > CollapsibleTitle, #skill-files-panel > CollapsibleTitle { display: none; }
    #catalog.-collapsed { display: none; }
    #detail { width: 1fr; padding: 1 2; }
    #filter { margin: 1 1 0 1; }
    #skills { height: 1fr; margin: 1; }
    #skill-content { height: 1fr; }
    #skill-files-panel { width: 30%; min-width: 24; height: 1fr; margin-right: 1; padding: 0; }
    #skill-files-panel.-collapsed { display: none; }
    #skill-files { height: 1fr; border: round $secondary; }
    #viewer-pane { width: 1fr; }
    #metadata { height: auto; color: $accent; border: round $secondary; padding: 0 1; }
    #status { color: $text-muted; margin-top: 1; }
    #output { height: 1fr; margin-top: 0; border: round $secondary; }
    """
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("a", "search", "Search & install"),
        ("u", "update", "Update"),
        ("r", "remove", "Remove"),
        ("f", "search", "Search & install"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("b", "toggle_catalog", "Skills"),
        ("d", "toggle_files", "Files"),
        ("t", "toggle_contents", "Contents"),
        ("slash", "focus_filter", "Filter"),
        ("enter", "view", "View"),
        ("ctrl+r", "refresh", "Refresh"),
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        catalog_loader: Callable[[], list[Skill]] = load_global_skills,
        *,
        load_on_mount: bool = True,
    ) -> None:
        super().__init__()
        self.catalog_loader = catalog_loader
        self.load_on_mount = load_on_mount
        self.skills: list[Skill] = []
        self.filtered_skills: list[Skill] = []
        self.active_skill_path: Path | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Collapsible(title="", collapsed=False, id="catalog"):
                yield SearchInput(placeholder="Filter skills…", id="filter")
                yield ListView(id="skills")
            with Vertical(id="detail"), Horizontal(id="skill-content"):
                with Collapsible(title="", collapsed=True, id="skill-files-panel"):
                    yield DirectoryTree(Path("."), id="skill-files")
                with Vertical(id="viewer-pane"):
                    yield Static(
                        "Select a skill to view its metadata and instructions.",
                        id="metadata",
                    )
                    yield Static("Ready", id="status")
                    yield MarkdownViewer("", show_table_of_contents=False, id="output")
        yield Footer()

    def on_mount(self) -> None:
        if self.load_on_mount:
            self.refresh_catalog()
        self.query_one("#filter", Input).focus()

    @on(Input.Changed, "#filter")
    def filter_skills(self, event: Input.Changed) -> None:
        query = event.value.casefold().strip()
        self.filtered_skills = [
            s for s in self.skills if query in f"{s.name} {s.description}".casefold()
        ]
        self.render_list()

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_cursor_down(self) -> None:
        view = self.query_one("#skills", ListView)
        view.focus()
        view.action_cursor_down()

    def action_cursor_up(self) -> None:
        view = self.query_one("#skills", ListView)
        view.focus()
        view.action_cursor_up()

    @on(ListView.Selected, "#skills")
    def select_skill(self, event: ListView.Selected) -> None:
        if isinstance(event.item, SkillItem):
            self.show_skill(event.item.skill)

    def action_toggle_catalog(self) -> None:
        panel = self.query_one("#catalog", Collapsible)
        panel.collapsed = not panel.collapsed

    def action_toggle_files(self) -> None:
        panel = self.query_one("#skill-files-panel", Collapsible)
        panel.collapsed = not panel.collapsed

    def action_toggle_contents(self) -> None:
        viewer = self.query_one("#output", MarkdownViewer)
        viewer.show_table_of_contents = not viewer.show_table_of_contents

    @on(DirectoryTree.FileSelected, "#skill-files")
    def open_skill_file(self, event: DirectoryTree.FileSelected) -> None:
        self.show_file(event.path)

    def render_list(self, *, select_first: bool = False) -> None:
        view = self.query_one("#skills", ListView)
        view.clear()
        view.extend(SkillItem(skill) for skill in self.filtered_skills)
        if self.filtered_skills:
            active_index = next(
                (
                    index
                    for index, skill in enumerate(self.filtered_skills)
                    if skill.path == self.active_skill_path
                ),
                0,
            )
            view.index = active_index
            if select_first and self.active_skill_path is None:
                self.show_skill(self.filtered_skills[active_index])
        else:
            self.query_one("#metadata", Static).update("No matching skills")

    def refresh_catalog(self) -> None:
        self.load_catalog_from_cli()

    @work(thread=True, exclusive=True)
    def load_catalog_from_cli(self) -> None:
        self.call_from_thread(
            self.query_one("#status", Static).update, "Loading global skills from npx…"
        )
        try:
            skills = self.catalog_loader()
        except (
            OSError,
            RuntimeError,
            ValueError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
        ) as error:
            self.call_from_thread(self.catalog_failed, str(error))
            return
        self.call_from_thread(self.catalog_loaded, skills)

    def catalog_loaded(self, skills: list[Skill]) -> None:
        self.skills = skills
        self.filtered_skills = self.skills
        if self.active_skill_path and not any(
            skill.path == self.active_skill_path for skill in skills
        ):
            self.active_skill_path = None
        self.render_list(select_first=True)
        self.query_one(
            "#filter", Input
        ).placeholder = f"Filter {len(self.skills)} global skills…"
        self.query_one("#status", Static).update("")

    def catalog_failed(self, error: str) -> None:
        self.query_one("#status", Static).update(
            f"Could not load npx skills list: {error}"
        )

    def selected(self) -> Skill | None:
        child = self.query_one("#skills", ListView).highlighted_child
        return child.skill if isinstance(child, SkillItem) else None

    def show_skill(self, skill: Skill) -> None:
        if skill.path != self.active_skill_path:
            self.active_skill_path = skill.path
            self.query_one("#skill-files", DirectoryTree).path = skill.path
        self.show_file(skill.path / "SKILL.md")

    def show_file(self, path: Path) -> None:
        """Render a selected skill file without exposing its absolute path in the UI."""
        metadata = "No frontmatter metadata."
        try:
            content = path.read_text(encoding="utf-8")
            if path.name == "SKILL.md":
                metadata, content = split_frontmatter(content)
            elif path.suffix.lower() not in {".md", ".mdx"}:
                language = path.suffix.removeprefix(".")
                content = f"```{language}\n{content}\n```"
        except OSError as error:
            content = f"# Could not read {path.name}\n\n{error}"
        self.query_one("#metadata", Static).update(metadata)
        self.update_markdown(
            content or "This skill has no instructions after its frontmatter."
        )

    @work(exclusive=True)
    async def update_markdown(self, content: str) -> None:
        """Await MarkdownViewer updates so its content and TOC stay in sync."""
        await self.query_one("#output", MarkdownViewer).document.update(content)

    def action_refresh(self) -> None:
        self.refresh_catalog()

    def action_view(self) -> None:
        if skill := self.selected():
            self.show_skill(skill)

    def action_search(self) -> None:
        self.push_screen(SearchInstallScreen())

    def action_update(self) -> None:
        if skill := self.selected():
            self.run_command(
                ["npx", "skills", "update", "--global", "--yes", skill.name]
            )

    def action_remove(self) -> None:
        if skill := self.selected():
            command = ["npx", "skills", "remove", "--global", "--yes", skill.name]

            def complete_removal(confirmed: bool | None) -> None:
                if confirmed:
                    self.run_command(command)

            self.push_screen(ConfirmRemove(skill.name), complete_removal)

    @work(thread=True)
    def run_command(self, command: list[str]) -> None:
        display = "$ " + shlex.join(command)
        self.call_from_thread(
            self.query_one("#status", Static).update, f"Running: {display}"
        )
        try:
            result = subprocess.run(
                command, text=True, capture_output=True, timeout=180, check=False
            )
            output = (
                result.stdout + result.stderr
            ).strip() or "Command completed with no output."
            status = f"Finished with exit code {result.returncode}"
        except (OSError, subprocess.TimeoutExpired) as error:
            output, status = str(error), "Command failed"
        self.call_from_thread(
            self.update_markdown, f"```text\n{display}\n\n{output}\n```"
        )
        self.call_from_thread(self.query_one("#status", Static).update, status)
        self.call_from_thread(self.refresh_catalog)


def main() -> None:
    SkillsManager().run()
