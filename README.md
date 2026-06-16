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

- `REVIEW_LANGUAGE`: レビューコメント言語（`ja` または `en`、デフォルト: `ja`）
- `GITLAB_ALLOWED_HOSTS`: 許可するGitLabホスト名のカンマ区切り（デフォルト: `gitlab.com`）

## 実行

```bash
python main.py --repo-root .
```

ドライラン:

```bash
python main.py --repo-root . --dry-run
```

## ルール・除外設定

- `rules.md`: LLMのシステムプロンプトに追加されるプロジェクト規約
- `.reviewignore`: レビュー対象外ファイルのglobパターン

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
