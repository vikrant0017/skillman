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
