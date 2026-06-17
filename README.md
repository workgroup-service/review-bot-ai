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
- `GITLAB_ALLOWED_HOSTS`: 許可するGitLabホスト名のカンマ区切り（デフォルト: `gitlab.com`）
- `LLM_BLOCKED_PATHS`: LLM送信を禁止するファイルパターンのカンマ区切り（例: `secrets/**,**/*.pem`）

## Security Defaults

- `GITLAB_URL` は `https` 必須、かつ `GITLAB_ALLOWED_HOSTS` の allowlist に含まれるホストのみ許可されます。
- `rules.md` と diff は LLM送信前にシークレットパターンをマスキングします（token/password/JWT/private key など）。
- `LLM_BLOCKED_PATHS` に一致するファイルはレビュー対象から除外され、外部LLMへ送信されません。
- `.env` はGit管理対象外です。トークンや秘密情報は `.env` のみに保存してください。
- 現在の実装で実運用可能な組み合わせは `REVIEW_PLATFORM=gitlab` と `LLM_PROVIDER=openai` のみです。
- `LLM_PROVIDER=openapi` / `open-api` / `open_api` は `openai` として扱われます。

## 実行

```bash
python main.py --repo-root .
```

ドライラン:

```bash
python main.py --repo-root . --dry-run
```

`--dry-run` は GitLab への投稿のみ抑止し、差分取得・LLMレビュー・重複判定は実行されます。

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
