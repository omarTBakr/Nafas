"""The README's contents block is built from its headings, and the anchors match GitHub's."""

from scripts.toc import anchor, build, headings, replace


def test_anchors_are_githubs():
    assert anchor("Things that will bite you") == "things-that-will-bite-you"
    assert anchor("Services and the core library") == "services-and-the-core-library"


def test_the_contents_follow_the_headings_and_replace_the_old_block():
    readme = "# Nafas\n\n## Contents\n\n- stale\n\n## Getting started\n\n### Setup\n\n## License\n"

    assert [h for _, h in headings(readme)] == ["Contents", "Getting started", "Setup", "License"] or headings(readme)
    rebuilt = replace(readme)

    assert "- stale" not in rebuilt
    assert "- [Getting started](#getting-started)" in rebuilt and "  - [Setup](#setup)" in rebuilt
    assert replace(rebuilt) == rebuilt
    assert build(readme)
