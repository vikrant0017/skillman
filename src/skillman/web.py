"""Minimal read-only HTML page that renders the installed skills."""

from __future__ import annotations

import sys
from collections.abc import Callable
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from skillman import Skill, load_global_skills, split_frontmatter


def render_page(skills: list[Skill]) -> str:
    sections = []
    for skill in skills:
        try:
            metadata, body = split_frontmatter(
                (skill.path / "SKILL.md").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError) as error:
            metadata, body = "", f"Could not read SKILL.md: {error}"
        sections.append(
            f'<details id="{escape(skill.name, quote=True)}"><summary>'
            f"<b>{escape(skill.name)}</b> &mdash; {escape(skill.description)}"
            f"</summary><pre>{escape(metadata)}</pre><pre>{escape(body)}</pre></details>"
        )
    return (
        "<!doctype html><meta charset=utf-8><title>Skillman</title>"
        "<style>body{font:15px system-ui;max-width:60rem;margin:2rem auto}"
        "pre{white-space:pre-wrap;background:#f4f4f4;padding:.5rem}</style>"
        f"<h1>Skillman</h1><p>{len(skills)} global skills</p>" + "".join(sections)
    )


def make_server(
    loader: Callable[[], list[Skill]] = load_global_skills,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/":
                self.send_error(404)
                return
            try:
                body = render_page(loader()).encode()
                self.send_response(200)
            except (OSError, RuntimeError, ValueError) as error:
                body = f"Could not load skills: {escape(str(error))}".encode()
                self.send_response(500)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = make_server(port=port)
    print(f"Serving skills at http://127.0.0.1:{port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
