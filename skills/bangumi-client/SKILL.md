---
name: "bangumi-client"
description: "Fetches Bangumi subject details (score, count) and recent short comments (tags/tucao). Invoke when user asks for subject info or comments."
---

# Bangumi Client

This skill retrieves detailed information about a Bangumi subject, including:
1.  **Rating Score**
2.  **Rating Count**
3.  **Recent Short Comments** (up to 20)

It combines data from the official API (v0) and web scraping to provide comprehensive details.

## Usage

To use this skill, run the provided Python script with a Subject ID or URL.

### Command

```bash
python3 skills/bangumi-client/fetch_bangumi.py <subject_id_or_url> --token <optional_token> [--limit <number>] [--all]
```

### Options

- `--limit N`: Fetch N comments (default: 20).
- `--all`: Fetch ALL comments (automatically handles pagination).
- `--offset N`: Start fetching from offset N.
- `--token TOKEN`: Use a specific API token.

### Examples

- Get info for Subject ID 127832:
  ```bash
  python3 skills/bangumi-client/fetch_bangumi.py 127832
  ```

- Get ALL comments for a subject:
  ```bash
  python3 skills/bangumi-client/fetch_bangumi.py 127832 --all
  ```

- Get info for a URL:
  ```bash
  python3 skills/bangumi-client/fetch_bangumi.py https://bgm.tv/subject/127832
  ```

- Use with a token (recommended for higher rate limits):
  ```bash
  python3 skills/bangumi-client/fetch_bangumi.py 127832 --token your_token
  # OR
  export BANGUMI_TOKEN=your_token
  python3 skills/bangumi-client/fetch_bangumi.py 127832
  ```

## Output Format

The script outputs a JSON object containing:
- `subject_id`: The ID of the subject.
- `title`: The name of the subject.
- `rating`: Object with `score` and `count`.
- `comments`: Array of comment objects with `user`, `rating`, and `content`.
