from skitter.transports.discord import (
    DISCORD_MESSAGE_CHAR_LIMIT,
    _prepare_discord_content,
    _split_discord_content,
)


def test_prepare_discord_content_wraps_links_when_three_or_more() -> None:
    content = (
        "References:\n"
        "- https://example.com/a\n"
        "- https://example.com/b\n"
        "- https://example.com/c\n"
    )

    formatted = _prepare_discord_content(content)

    assert "<https://example.com/a>" in formatted
    assert "<https://example.com/b>" in formatted
    assert "<https://example.com/c>" in formatted


def test_prepare_discord_content_leaves_two_links_unchanged() -> None:
    content = "See https://example.com/a and https://example.com/b"
    formatted = _prepare_discord_content(content)
    assert formatted == content


def test_split_discord_content_prefers_sentence_boundaries() -> None:
    sentence = "This is a complete sentence with enough text to force smart boundary splits. "
    content = sentence * 120

    chunks = _split_discord_content(content, DISCORD_MESSAGE_CHAR_LIMIT)

    assert all(len(chunk) <= DISCORD_MESSAGE_CHAR_LIMIT for chunk in chunks)
    assert "".join(chunks) == content
    assert len(chunks) > 1
    for chunk in chunks[:-1]:
        assert chunk.rstrip().endswith(".")


def test_split_discord_content_keeps_list_structure_with_nested_links() -> None:
    lines = []
    for i in range(1, 80):
        lines.append(f"- Topic {i}: https://example.com/{i}\n")
        lines.append(f"  - Reference {i}: https://docs.example.com/{i}\n")
    content = "".join(lines)
    prepared = _prepare_discord_content(content)

    chunks = _split_discord_content(prepared, DISCORD_MESSAGE_CHAR_LIMIT)

    assert all(len(chunk) <= DISCORD_MESSAGE_CHAR_LIMIT for chunk in chunks)
    assert "".join(chunks) == prepared
    assert len(chunks) > 1
    for chunk in chunks[:-1]:
        assert chunk.endswith("\n")
