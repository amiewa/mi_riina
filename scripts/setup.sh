#!/bin/bash
# 初回セットアップスクリプト
# 全 .example ファイルを実ファイルにコピーする（既存ファイルはスキップ）
set -euo pipefail

FILES=(
    ".env"
    "config/config.yaml"
    "config/character_prompt.md"
    "config/reaction_rules.yaml"
    "config/serif/scheduled.yaml"
    "config/serif/weekday_posts.yaml"
    "config/serif/random.yaml"
    "config/serif/fallback.yaml"
    "config/serif/poll.yaml"
    "config/serif/event.yaml"
)

for f in "${FILES[@]}"; do
    if [ ! -f "$f" ] && [ -f "${f}.example" ]; then
        cp "${f}.example" "$f"
        echo "Created: $f"
    elif [ -f "$f" ]; then
        echo "Skipped (already exists): $f"
    else
        echo "Warning: ${f}.example not found"
    fi
done

echo "Setup complete. Edit the files above to match your environment."
