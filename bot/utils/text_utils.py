"""テキスト処理ユーティリティ

タイムライン連動投稿やアンケートで使用する、ワード選択等の共通処理。
"""

import random

def weighted_keyword_choice(keywords: list[str], k: int = 1) -> list[str]:
    """長いワードほど選ばれやすい重み付きランダム選択。

    重み = len(keyword) - 1  (2文字→1, 3文字→2, 5文字→4, ...)
    k >= len(keywords) の場合は全件返す。

    Args:
        keywords: ユニーク済みのキーワードリスト
        k: 選択数

    Returns:
        選択されたキーワードのリスト（重複なし）
    """
    if not keywords:
        return []
    if k >= len(keywords):
        return list(keywords)

    weights = [max(len(kw) - 1, 1) for kw in keywords]
    selected: list[str] = []
    remaining = list(enumerate(keywords))
    remaining_weights = list(weights)

    for _ in range(k):
        if not remaining:
            break
        chosen = random.choices(range(len(remaining)), weights=remaining_weights, k=1)[0]
        selected.append(remaining[chosen][1])
        remaining.pop(chosen)
        remaining_weights.pop(chosen)

    return selected
