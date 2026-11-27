from pathlib import Path

import pytest

import skillman
from skillman import (
    SearchSkill,
    frontmatter_value,
    install_global_skill,
    skills_from_cli_json,
    split_frontmatter,
)


def test_frontmatter_value_reads_quoted_values() -> None:
    text = "---\nname: 'demo'\ndescription: A useful skill\n---\n# Demo\n"
    assert frontmatter_value(text, "name") == "demo"
    assert frontmatter_value(text, "description") == "A useful skill"


def test_cli_json_builds_sidebar_records() -> None:
    skills = skills_from_cli_json(
        '[{"name":"demo","description":"Demonstration","path":"/tmp/demo"}]'
    )
    assert [(skill.name, skill.description, skill.path) for skill in skills] == [
        ("demo", "Demonstration", Path("/tmp/demo"))
    ]


def test_split_frontmatter_hides_yaml_from_instruction_body() -> None:
    metadata, body = split_frontmatter(
        "---\nname: demo\ndescription: Useful\n---\n# Instructions\n"
    )
    assert metadata == "name: demo\ndescription: Useful"
    assert body == "# Instructions\n"


def test_install_uses_source_and_skill_id(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_run(command: list[str], **_kwargs: object) -> object:
        captured.extend(command)
        return type("Result", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    monkeypatch.setattr(skillman.subprocess, "run", fake_run)
    result = SearchSkill("owner/repo/demo", "demo", "demo", 42, "owner/repo")

    code = install_global_skill(result)

    assert code == 0
    assert captured == [
        "npx",
        "skills",
        "add",
        "owner/repo",
        "--skill",
        "demo",
        "--global",
        "--yes",
    ]


def test_search_tolerates_null_installs(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    body = b'{"skills":[{"id":"a/b/c","skillId":"c","name":"c","source":"a/b","installs":null}]}'
    monkeypatch.setattr(skillman, "urlopen", lambda *_a, **_k: io.BytesIO(body))

    [result] = skillman.search_skills_api("c")

    assert result.installs == 0


@pytest.mark.parametrize("source,skill_id", [("--evil", "demo"), ("owner/repo", "-x")])
def test_install_rejects_option_like_values(source: str, skill_id: str) -> None:
    with pytest.raises(ValueError):
        install_global_skill(SearchSkill("id", skill_id, "demo", 1, source))


@pytest.mark.asyncio
async def test_selecting_binary_file_does_not_crash(tmp_path: Path) -> None:
    binary = tmp_path / "logo.png"
    binary.write_bytes(b"\x89PNG\xff\xfe\x00")
    app = skillman.SkillsManager(load_on_mount=False)
    async with app.run_test() as pilot:
        app.show_file(binary)
        await pilot.pause()
        assert app.is_running


@pytest.mark.asyncio
async def test_install_requires_confirmation() -> None:
    installed: list[str] = []
    skill = SearchSkill("a/b/c", "c", "c", 1, "a/b")
    screen = skillman.SearchInstallScreen(
        searcher=lambda _q: [skill],
        installer=lambda s: installed.append(s.skill_id) or 0,
        refresh_catalog=lambda: None,
    )
    app = skillman.SkillsManager(load_on_mount=False)
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        screen.show_results([skill])
        await pilot.pause()

        await pilot.press("enter")  # select result -> confirmation modal
        await pilot.pause()
        assert isinstance(app.screen, skillman.ConfirmInstall)
        await pilot.press("enter")  # default focus is Cancel
        await pilot.pause()
        assert installed == []
        assert app.screen is screen

        await pilot.press("enter")
        await pilot.pause()
        await pilot.click("#install")
        for _ in range(50):
            if installed:
                break
            await pilot.pause(0.1)
        assert installed == ["c"]
