import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from skillman import Skill
from skillman.web import make_server


def test_page_renders_and_escapes_skills(tmp_path: Path) -> None:
    (tmp_path / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo\n---\n# Body <script>x</script>\n"
    )
    skills = [Skill("demo", "A <b>demo</b>", tmp_path, None)]
    server = make_server(lambda: skills, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        html = urlopen(base + "/", timeout=5).read().decode()
        assert "demo" in html and "1 global skills" in html
        assert "# Body &lt;script&gt;" in html and "<script>x" not in html
        assert "A &lt;b&gt;demo" in html
        with pytest.raises(HTTPError) as info:
            urlopen(base + "/other", timeout=5)
        assert info.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
