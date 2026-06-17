<!-- @author Cursor -->
# review-bot

GitLabのマージリクエストを対象に、`gpt-5.3-codex` を使ってインラインコードレビューを投稿するPython CLIです。

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 必須環境変数

- `GITLAB_TOKEN`
- `PROJECT_ID`
- `MR_IID`
- `OPENAI_API_KEY`

## 任意環境変数

- `REVIEW_PLATFORM`: レビュープラットフォーム（`gitlab`、将来 `github` 対応予定）
- `LLM_PROVIDER`: LLMプロバイダ（`openai`、将来 `anthropic` 対応予定）
- `REVIEW_LANGUAGE`: レビューコメント言語（`ja` または `en`、デフォルト: `ja`）
- `OUTPUT_MODE`: 投稿モード（`inline` / `summary` / `both`、デフォルト: `inline`）
- `SUMMARY_MAX_LINES`: サマリー最大行数（デフォルト: `30`）
- `SUMMARY_MAX_CHARS`: サマリー最大文字数（デフォルト: `3000`）
- `GITLAB_ALLOWED_HOSTS`: 許可するGitLabホスト名のカンマ区切り（デフォルト: `gitlab.com`）
- `LLM_BLOCKED_PATHS`: LLM送信を禁止するファイルパターンのカンマ区切り（例: `secrets/**,**/*.pem`）

## Security Defaults

- `GITLAB_URL` は `https` 必須、かつ `GITLAB_ALLOWED_HOSTS` の allowlist に含まれるホストのみ許可されます。
- `rules.md` と diff は LLM送信前にシークレットパターンをマスキングします（token/password/JWT/private key など）。
- `LLM_BLOCKED_PATHS` に一致するファイルはレビュー対象から除外され、外部LLMへ送信されません。
- `.env` はGit管理対象外です。トークンや秘密情報は `.env` のみに保存してください。
- 現在の実装で実運用可能な組み合わせは `REVIEW_PLATFORM=gitlab` と `LLM_PROVIDER=openai` のみです。
- `LLM_PROVIDER=openapi` / `open-api` / `open_api` は `openai` として扱われます。
- `OUTPUT_MODE=summary` または `both` の場合、同一MR上のサマリーノートを更新（upsert）します。

## 実行

```bash
python main.py --repo-root .
```

設定ファイルを指定する場合:

```bash
python main.py --config ./configs/review-bot.env --repo-root .
```

ルール・除外ファイルを外部指定する場合:

```bash
python main.py \
  --repo-root . \
  --rules-file ./config/review-rules.md \
  --reviewignore-file ./config/reviewignore.txt
```

ドライラン:

```bash
python main.py --repo-root . --dry-run
```

`--dry-run` は GitLab への投稿のみ抑止し、差分取得・LLMレビュー・重複判定は実行されます。

`--config` が未指定の場合は `.env` を読み込みます。指定ファイルが存在しない、または `KEY=VALUE` 形式でない行を含む場合はエラー終了します。
`--rules-file` と `--reviewignore-file` が未指定の場合は、`--repo-root` 配下の `rules.md` / `.reviewignore` を利用します。

## ルール・除外設定

- `rules.md`: LLMのシステムプロンプトに追加されるプロジェクト規約
- `rules.d/*.md`: 追加ルールをファイル分割して読み込み可能（ファイル名昇順で連結）
- `.reviewignore`: レビュー対象外ファイルのglobパターン
  - `!` で否定パターンを指定可能（後勝ち評価）

サンプル:

- [rules.md.example](rules.md.example)
- [.reviewignore.example](.reviewignore.example)

## GitLab CI 例

```yaml
review_bot:
  image: python:3.11
  stage: test
  script:
    - pip install -r requirements.txt
    - python main.py --repo-root .
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
  variables:
    PROJECT_ID: "$CI_PROJECT_ID"
    MR_IID: "$CI_MERGE_REQUEST_IID"
    GITLAB_URL: "$CI_SERVER_URL"
    GITLAB_ALLOWED_HOSTS: "gitlab.com,gitlab.example.com"
```

## Exit code

- 設定不備・致命的失敗: 非0
- レビュー実行完了（指摘有無問わず）: 0
