"""`CLAUDE.md` has to stay a link to `AGENTS.md`, and what AGENTS.md
points to has to be there.

`/code-review`'s conventions check reads only `CLAUDE.md` files, so deleting the
link stops the review checking the repo's rules, and a regular copy lets the
two drift. Nothing else would fail. A Windows clone without
`core.symlinks=true` fails here too: the link arrives as a text file.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class ClaudeMdIsALinkTests(SimpleTestCase):
    def test_claude_md_links_to_agents_md(self):
        link = Path(settings.BASE_DIR) / "CLAUDE.md"
        self.assertTrue(link.is_symlink(), "CLAUDE.md must be a symlink")
        self.assertEqual(link.readlink(), Path("AGENTS.md"))


BASE = Path(settings.BASE_DIR)
AGENTS = BASE / "AGENTS.md"
TOPICS = BASE / "docs" / "agents"
POINTER = re.compile(r"`(docs/agents/[\w-]+\.md)`")
# How code and the other documents cite a section: AGENTS.md, "Caching" or
# "Caching" in AGENTS.md
CITATIONS = (
    re.compile(r'AGENTS\.md,\s+(?:#\s+|//\s+|\*\s+)?"([^"]+)"'),
    re.compile(r'"([^"]+)"\s+in\s+`?AGENTS\.md'),
)
SKIPPED_DIRS = {
    "node_modules",
    "staticfiles",
    "venv",
    ".git",
    ".context",
    ".claude",
    "htmlcov",
    "media",
}
CITING = {".py", ".js", ".html", ".sh", ".md", ".yml", ".in", ".example", ".css"}


class AgentsMdIsRulesAndPointersTests(SimpleTestCase):
    """AGENTS.md holds the rules; `docs/agents/` holds the reasons.

    It loads into every agent session, and `/code-review` checks a change
    against it alone. By 2026-11-12 it was 200 KB, most of it the history
    and measurements behind its rules. Those moved, word for word, to a
    file a section, which the section names.
    """

    def test_every_file_a_section_points_to_exists(self):
        pointers = set(POINTER.findall(AGENTS.read_text()))
        self.assertGreater(len(pointers), 15)
        for pointer in sorted(pointers):
            with self.subTest(pointer=pointer):
                self.assertTrue((BASE / pointer).is_file())

    def test_every_topic_file_is_pointed_to(self):
        """A file nothing names is a file nobody is sent to read."""
        pointers = set(POINTER.findall(AGENTS.read_text()))
        for path in sorted(TOPICS.glob("*.md")):
            with self.subTest(file=path.name):
                self.assertIn(f"docs/agents/{path.name}", pointers)

    def test_a_section_cited_elsewhere_is_still_a_section(self):
        """Code comments and the other documents cite sections by name:
        `AGENTS.md, "Caching"`. A renamed heading would strand them."""
        text = AGENTS.read_text()
        cited = {}
        for path in BASE.rglob("*"):
            if SKIPPED_DIRS.intersection(path.relative_to(BASE).parts):
                continue
            if not path.is_file() or path.suffix not in CITING:
                continue
            if path == AGENTS or TOPICS in path.parents or path.name == "DEVLOG.md":
                continue
            # Line ends inside a citation are part of it
            source = " ".join(path.read_text(errors="ignore").split())
            for pattern in CITATIONS:
                for name in pattern.findall(source):
                    cited.setdefault(name, path.relative_to(BASE).as_posix())
        self.assertGreater(len(cited), 5, cited)
        for name, where in sorted(cited.items()):
            with self.subTest(section=name, cited_by=where):
                self.assertIn(name, text)

    def test_it_has_not_grown_back(self):
        """The rule goes here and the account of why in the section's
        file. 64 KB is half again what it weighed when it was split."""
        self.assertLess(
            len(AGENTS.read_bytes()),
            64 * 1024,
            "AGENTS.md loads into every session: move the reasoning and "
            "history to the section's docs/agents file, and keep the rule.",
        )
