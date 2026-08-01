from utils.coze_plugin_tools import split_text_segments


def test_caption_split_prefers_clause_boundaries_without_breaking_phrases():
    assert split_text_segments(
        "真正拉开人与人差距的，不是聪明，而是长期主义。",
        min_len=1,
        max_len=12,
    ) == ["真正拉开人与人差距的", "不是聪明，而是长期主义"]


def test_caption_split_keeps_unpunctuated_chinese_semantics_together():
    text = "不要让短期情绪破坏你的长期目标"

    assert split_text_segments(text, min_len=1, max_len=8) == [text]


def test_caption_split_uses_word_boundaries_for_english():
    assert split_text_segments(
        "Build the habit before you chase the result.",
        min_len=1,
        max_len=15,
    ) == ["Build the habit", "before you", "chase the", "result"]
