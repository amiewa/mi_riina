"""テキストクリーニングユーティリティ

ノート本文から URL・メンション・カスタム絵文字等を除去する。
タイムライン連動投稿・ワードクラウド・アンケートの3機能から共通利用する。
"""

import re

# 各種パターン
_URL_PATTERN = re.compile(r"https?://\S+")
_MENTION_PATTERN = re.compile(r"@\w+(@[\w.]+)?")
_CUSTOM_EMOJI_PATTERN = re.compile(r":[\w]+:")
_HASHTAG_PATTERN = re.compile(r"#\S+")

# コードブロック
_CODE_BLOCK_PATTERN = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_PATTERN = re.compile(r"`.*?`")

# MFM: $[tag content] 形式
# タグ名部分 ([^\\s\\]]+) は英数字以外（ドットや等号）を含む可能性があるため修正
# タグ部分 ($[tag と 末尾の ]) を除去し、コンテンツ部分を保持する
# 入れ子になる場合があるため、ループで内側から順に処理する
_MFM_TAG_PATTERN = re.compile(r"\$\[[^\s\]]+\s+([^\[\]]*?)\]")
# コンテンツなしの MFM ($[tag]) も除去
_MFM_EMPTY_PATTERN = re.compile(r"\$\[[^\s\]]+\]")


def clean_note_text(text: str | None) -> str:
    """ノート本文から URL・メンション・カスタム絵文字等を除去する。

    除去対象:
    - URL (https?://...)
    - メンション (@user@host)
    - カスタム絵文字 (:emoji:)
    - ハッシュタグ (#tag)
    - MFM 構文 ($[...])

    Args:
        text: 入力テキスト（None 可）

    Returns:
        クリーニング後のテキスト（空文字列になる可能性あり）
    """
    if not text:
        return ""

    text = _URL_PATTERN.sub("", text)
    text = _MENTION_PATTERN.sub("", text)
    text = _CUSTOM_EMOJI_PATTERN.sub("", text)
    text = _HASHTAG_PATTERN.sub("", text)

    # コードブロックを除去
    text = _CODE_BLOCK_PATTERN.sub("", text)
    text = _INLINE_CODE_PATTERN.sub("", text)

    # MFM: 入れ子対応（最大5回ループで内側から除去）
    for _ in range(5):
        # $[tag content] → content（コンテンツを保持）
        new_text = _MFM_TAG_PATTERN.sub(r"\1", text)
        # $[tag] → 空文字（コンテンツなし）
        new_text = _MFM_EMPTY_PATTERN.sub("", new_text)
        if new_text == text:
            break
        text = new_text

    return text.strip()
