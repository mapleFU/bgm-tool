---
name: "bangumi-analyzer"
description: "Analyzes Bangumi subject comments JSON output. Invoke when user wants to summarize reviews, get sentiment analysis, or extract insights from comments."
---

# Bangumi Comment Analyzer

This skill takes the JSON output from `bangumi-client` and uses an LLM (default: DeepSeek) to analyze and summarize the comments.

## Usage

1. **Fetch comments**:
   ```bash
   python3 skills/bangumi-client/fetch_bangumi.py <subject_id> > comments.json
   ```

2. **Analyze comments**:
   ```bash
   python3 skills/bangumi-analyzer/analyze_comments.py comments.json --api-key <your_api_key>
   ```

   Or pipe directly:
   ```bash
   python3 skills/bangumi-client/fetch_bangumi.py <subject_id> | python3 skills/bangumi-analyzer/analyze_comments.py --api-key <your_api_key>
   ```

## Arguments

- `input_file`: Path to the JSON file containing comments (optional if piping from stdin).
- `--api-key`: Your LLM API key (required, or set `LLM_API_KEY` env var).
- `--provider`: The LLM provider (default: `deepseek`). Currently supports `deepseek`, `stepfun`, and `openai-compatible`.
- `--base-url`: Custom API base URL (required for `openai-compatible`, optional for `stepfun` which defaults to `https://api.stepfun.com/v1`).
- `--model`: Model name (default: `deepseek-chat`). For `stepfun`, use `step-3.5-flash` or similar.
- `--batch-size`: Number of comments per batch for large files (default: 50). Automatically splits large inputs into chunks to avoid token limits.

## Output Format

The analysis will include:
1. **Positive Review Ratio & Key Points**: Percentage of positive reviews and main reasons.
2. **Negative Review Ratio & Key Points**: Percentage of negative reviews and main criticisms.
3. **Selected In-Depth Reviews**: A selection of high-quality, detailed comments.
4. **Overall Summary**: A comprehensive summary of the general sentiment and viewpoints.
