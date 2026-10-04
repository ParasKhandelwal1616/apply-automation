from apply_bot.telegram.browser import chat_root_url


def test_chat_root_keeps_chat_hash() -> None:
    assert (
        chat_root_url("https://web.telegram.org/k/#-3963315719")
        == "https://web.telegram.org/k/#-3963315719"
    )


def test_chat_root_strips_k_message_permalink() -> None:
    assert (
        chat_root_url("https://web.telegram.org/k/#-3963315719_888001")
        == "https://web.telegram.org/k/#-3963315719"
    )


def test_chat_root_strips_a_message_permalink() -> None:
    assert (
        chat_root_url("https://web.telegram.org/a/#-3963315719/888001")
        == "https://web.telegram.org/a/#-3963315719"
    )


def test_chat_root_rejects_non_telegram() -> None:
    assert chat_root_url("https://example.com/k/#-1") is None
