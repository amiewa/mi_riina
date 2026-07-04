# Misskey Bot Riina(りいな)

**Misskey 用キャラクター bot — Python + Docker で動作**

---

## 概要

- Riina(りいな)はMisskeyで動作するキャラクターBotです。
- [Misskey](https://github.com/misskey-dev/misskey) 2025.12.2 以降で動作を確認しています。

### 特徴

- **セルフホスト**: Debian + Docker compose で動作
- **LLMプロバイダ切替**: Gemini / Ollama / OpenRouter を機能別に使い分け可能
- **みあ互換設計**: [みあ](https://github.com/amiewa/mi_mia) と設定キー体系・機能を対称に設計

---

## 機能一覧

| 機能 | トリガー | LLM | デフォルト |
|------|---------|-----|----------|
| ランダム投稿 | 90分ごと | — | 有効 |
| 定時投稿 | 台詞ファイルで指定した時刻ごと | — | 有効 |
| 曜日別投稿 | 曜日・時刻が一致した時点（毎分判定） | — | 有効 |
| TL連動投稿 | 120分ごと | 選択可（`ai`モード時。`template`モードではLLM不要） | 有効 |
| 記念日イベント投稿 | 該当日の7〜21時にランダムな1回 | — | 有効 |
| 星座占い | 毎日7:00 | 選択可（`ai`モード時。`no_ai`モードではLLM不要） | 無効 |
| アンケート投稿 | 12時間ごと | 選択可（`ai`モード時。`tl_word`/`static`モードではLLM不要） | 無効 |
| ワードクラウド投稿 | 12時間ごと（生成）／WebSocket常時（ノート収集） | — | 無効 |
| メンション返信 | WebSocket（メンション受信時） | 必須（生成失敗・NGワード検出時等はフォールバック定型文） | 有効 |
| ニックネーム登録 | WebSocket（メンション受信時） | — | 有効 |
| マルチターン会話文脈 | メンション返信時 | — | 無効 |
| 親密度によるプロンプト調整 | メンション返信時 | — | 無効 |
| 自動リアクション | WebSocket（ノート受信時） | — | 有効 |
| フォロー同期・自動解除 | 30分ごと | — | 有効 |
| 自動フォローバック | WebSocket（フォロー検知時） | — | 無効 |
| キーワードフォローバック | WebSocket（メンション受信時） | — | 有効 |
| 投稿・ファイルの自動削除 | 日次（post_typeごとに設定した保持時間経過後） | — | post_type別（既定は random のみ有効・72h） |

> 夜間モード（`night_mode`、デフォルト 23:00〜5:00 で有効）が適用される投稿・リアクション系機能は、上記トリガーに加えてこの時間帯は実行がスキップされる。

---

## セットアップ方法
1. 当リポジトリをクローンします。
   ```bash
   git clone https://github.com/amiewa/mi_riina.git
   cd mi_riina
   ```
2. セットアップスクリプトを実行し、設定ファイルの雛形をコピーします。
   ```bash
   bash scripts/setup.sh
   ```
3. `.env` を開き、自身の環境に合わせて `MISSKEY_INSTANCE_URL` や `MISSKEY_API_TOKEN`、各種LLMのAPIキー等を設定します。
4. `config/config.yaml` を開き、投稿設定やAIプロバイダの設定を調整します。
5. `compose.yml` を開き、必要に応じてコンテナ設定を調整します。
6. Docker Compose を用いてコンテナを起動します。
   ```bash
   docker compose up -d
   ```

---

## `/admin` コマンドの使い方
Botの管理者は、Botへのメンションまたはリプライで以下のコマンドを送信することで、ステータス確認や強制投稿などの管理操作が行えます。
※使用するには `config.yaml` の `admin.usernames` に使用するアカウントのユーザー名が設定されている必要があります。

- `/admin status`: Botの現在のステータス（API利用状況や各機能のオン/オフ設定など）を表示します。
- `/admin post <post_type>`: 指定したタイプの投稿を強制的に実行します。
  - 対応しているタイプ: `random`, `scheduled`, `weekday`, `timeline`, `horoscope`, `wordcloud`, `poll`, `event`
- `/admin nickname <username>`: 指定したユーザーのBot内でのニックネーム登録情報を確認します。

## 参考にしたMisskey Bot
本プロジェクトは、以下のプロジェクトを参考にさせていただきました。深く感謝申し上げます。
- [藍ちゃん](https://github.com/syuilo/ai) 
- [アストロラーベちゃん](https://github.com/amanami-takumi/astrolabe_for_misskey_v2)
- [さんごちゃん](https://github.com/RoiARISE/sango_chan_bot)

## 参照プロジェクト
- [goodBadWordlist](https://github.com/sayonari/goodBadWordlist) NGワードリストとして利用
- [Rounded M+](https://github.com/google/fonts) [SIL OPEN FONT LICENSE Version 1.1](https://openfontlicense.org/open-font-license-official-text) デフォルトフォントとして利用

## 関連プロジェクト
- [Misskey Bot Mia(みあ)](https://github.com/amiewa/mi_mia) りいなと同等の機能をGASで実現する取り組みです。設定キー体系を対称に設計しています。

## ライセンス
本プロジェクトは [MIT License](LICENSE) です。
