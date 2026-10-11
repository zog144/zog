import re
import unittest
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_COMPONENT_MARKDOWN_PARTS = (
    "/tests/fixtures/",
    "/examples/",
    "/patches/",
)
INLINE_LINK = re.compile(r"\]\(([^)]+)\)")
REFERENCE_LINK = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)", re.MULTILINE)


def _target_token(value: str) -> str:
    value = value.strip()
    if value.startswith("<"):
        end = value.find(">")
        return value[: end + 1] if end >= 0 else value
    return value.split(None, 1)[0] if value else value


def _local_target(source: Path, raw: str) -> Path | None:
    raw = _target_token(raw)
    if raw.startswith("<") and raw.endswith(">"):
        raw = raw[1:-1]
    if not raw or raw.startswith("#") or raw.startswith("/"):
        return None
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw):
        return None
    raw = raw.split("#", 1)[0].split("?", 1)[0]
    if not raw:
        return None
    return (source.parent / unquote(raw)).resolve()


class DocumentationLayoutTests(unittest.TestCase):
    def test_program_documentation_is_centralized(self):
        offenders = []
        for path in (ROOT / "components").rglob("*.md"):
            rel = "/" + path.relative_to(ROOT).as_posix()
            if not any(part in rel for part in ALLOWED_COMPONENT_MARKDOWN_PARTS):
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [], f"ordinary documentation under components/: {offenders}")

    def test_docs_index_and_program_subdirectories_exist(self):
        self.assertTrue((ROOT / "docs" / "README.md").is_file())
        program_docs = [
            p for p in (ROOT / "docs").rglob("*.md")
            if p.name not in {"README.md", "DEVELOPMENT.md"}
        ]
        shallow = [p.relative_to(ROOT).as_posix() for p in program_docs if len(p.relative_to(ROOT / "docs").parts) < 2]
        self.assertEqual(shallow, [], f"program docs must live below docs/<program>/: {shallow}")

    def test_relative_markdown_links_resolve(self):
        missing = []
        for source in ROOT.rglob("*.md"):
            text = source.read_text(encoding="utf-8")
            targets = list(INLINE_LINK.findall(text)) + list(REFERENCE_LINK.findall(text))
            for raw in targets:
                target = _local_target(source, raw)
                if target is not None and not target.exists():
                    missing.append((source.relative_to(ROOT).as_posix(), raw))
        self.assertEqual(missing, [], f"broken relative Markdown links: {missing}")


if __name__ == "__main__":
    unittest.main()
