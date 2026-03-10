# Misskey Bot Riina(りいな)
- Riina(りいな)はMisskeyで動作するキャラクターBotです。
- [Misskey](https://github.com/misskey-dev/misskey) 2025.12.2 以降で動作を確認しています。

## できること
- ランダムでのタイムライン投稿（時間帯ごとの確率調整が可能）
- 指定時刻での定時投稿
- 曜日別やタイムラインの流れに連動した投稿
- 星座占い機能による占い結果の投稿
- タイムラインから抽出したワードクラウドの自動生成・投稿
- ユーザー参加型のアンケート自動作成・投稿
- メンションやリプライに対するLLM（Gemini / Ollama / OpenRouter）を利用した自動応答
- 交流回数（親密度）に応じたAIプロンプトの自動調整
- タイムラインのノートに対する自動リアクション
- フォローの検知と自動フォローバック・同期
- 記念日等に合わせたイベント投稿
- 過去の投稿や不要なドライブファイルの自動削除

## セットアップ方法
1. 当リポジトリをクローンします。
   ```bash
   git clone https://github.com/amiewa/mi_riina.git
   cd mi_riina
   ```
2. 設定ファイルの雛形をコピーします。
   ```bash
   cp .env.example .env
   cp config/config.yaml.example config/config.yaml
   ```
3. `.env` を開き、自身の環境に合わせて `MISSKEY_INSTANCE_URL` や `MISSKEY_API_TOKEN`、各種LLMのAPIキー等を設定します。
4. Docker Compose を用いてコンテナを起動します。
   ```bash
   docker compose up -d
   ```


## 参考にしたMisskey Bot
本プロジェクトは、以下のプロジェクトを参考にさせていただきました。深く感謝申し上げます。
- [藍ちゃん](https://github.com/syuilo/ai) 
- [アストロラーベちゃん](https://github.com/amanami-takumi/astrolabe_for_misskey_v2)
- [さんごちゃん](https://github.com/RoiARISE/sango_chan_bot)

## 参照プロジェクト
- [goodBadWordlist](https://github.com/sayonari/goodBadWordlist) NGワードリストとして利用
- [Rounded M+](https://github.com/google/fonts) [SIL OPEN FONT LICENSE Version 1.1](https://openfontlicense.org/open-font-license-official-text) デフォルトフォントとして利用

## 関連プロジェクト
- [Misskey Bot Mia(みあ)](https://github.com/amiewa/mi_mia) りいなと同等の機能をGASで実現する取り組みです。

## ライセンス
本プロジェクトは [MIT License](LICENSE) です。