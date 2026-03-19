# Project Context (bgm-exp)

## Goal
- Crawl entertainment/community sites to collect user comments (reviews), then summarize/analyze them with an LLM.

## Concept
- Split the project into two parts:
  - Crawlers: fetch comments from different sites and normalize into a shared JSON shape.
  - Analyzer: take the normalized JSON and generate a Chinese Markdown report (supports large inputs via batching + parallel calls).

## Data Flow
- Fetch JSON via a site-specific crawler under `skills/*-client/`.
- Analyze JSON via `skills/bangumi-analyzer/analyze_comments.py`.

## Supported Sources
- Bangumi (anime / light novel / game):
  - Client: `skills/bangumi-client/fetch_bangumi.py`
  - Metadata: Bangumi Public API v0
  - Comments: Bangumi Private API `https://next.bgm.tv/p1/subjects/{subject_id}/comments` (pagination + `--all`)
- freem (ふりーむ！):
  - Client: `skills/freem-client/fetch_freem.py`
  - Strategy: try JSON API candidates first, fallback to HTML scraping of `/review/game/win/{id}` (pagination)
- freegame-mugen:
  - Client: `skills/freegame-mugen-client/fetch_freegame_mugen.py`
  - Strategy: parse embedded comments on `game_{id}.html`, optionally fetch `comment_{id}.html` for more
- DLsite:
  - Client: `skills/dlsite-client/fetch_dlsite.py`
  - Strategy: prefer official JSON endpoints (`/product/info/ajax` + `/api/review`), fallback to HTML for title
- Kakuyomu (カクヨム):
  - Client: `skills/kakuyomu-client/fetch_kakuyomu.py`
  - Strategy: use official GraphQL endpoint (`https://kakuyomu.jp/graphql`) for work metadata + review pagination

## Normalized Comment JSON Shape
- Top-level: `source`, `<id>`, `url`, `title`, `rating`, `comments_count`, `comments`
- Each comment (minimum): `user`, `rating`, `date`, `content`
- Optional: `status`, per-site ids, extra fields (e.g., freem review title / freegame-mugen subscores)

## LLM Analysis
- File: `skills/bangumi-analyzer/analyze_comments.py`
- Formats comments into a compact prompt.
- Large inputs: split into batches (`--batch-size`), summarize each batch, then produce a final report.
- Batch mode uses parallel calls with a hardcoded concurrency of 3.
- Providers: `deepseek`, `stepfun`, `openai-compatible` (Chat Completions compatible base URL).

## Handy Commands
- Bangumi:
  - `python3 skills/bangumi-client/fetch_bangumi.py <subject_id> --all --output bangumi_<id>.json`
- freem:
  - `python3 skills/freem-client/fetch_freem.py <id_or_url> --all --output freem_<id>.json`
- freegame-mugen:
  - `python3 skills/freegame-mugen-client/fetch_freegame_mugen.py <id_or_url> --all --output freegame_mugen_<id>.json`
- DLsite:
  - `python3 skills/dlsite-client/fetch_dlsite.py <id_or_url> --all --output dlsite_<product_id>.json`
- Kakuyomu:
  - `python3 skills/kakuyomu-client/fetch_kakuyomu.py <id_or_url> --all --output kakuyomu_<work_id>.json`
- Analyze (any source):
  - `python3 skills/bangumi-analyzer/analyze_comments.py <file.json> --api-key <KEY> --provider deepseek`
