import argparse
import json
import os
import re
import sys
import time
import pathlib

import requests
from bs4 import BeautifulSoup


try:
    from http_common import get_default_headers
except Exception:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from http_common import get_default_headers

HEADERS = get_default_headers("freem-client")

GAME_URL_PATTERN = r"/win/game/(\d+)"
REVIEW_URL_PATTERN = r"/review/game/win/(\d+)"


def get_game_id(arg):
    m = re.search(GAME_URL_PATTERN, arg)
    if m:
        return m.group(1)
    m = re.search(REVIEW_URL_PATTERN, arg)
    if m:
        return m.group(1)
    if arg.isdigit():
        return arg
    return None


def _get(url, *, params=None, timeout=30):
    return requests.get(url, headers=HEADERS, params=params, timeout=timeout)


def try_fetch_reviews_api(game_id, *, limit=20, fetch_all=False):
    candidates = [
        f"https://www.freem.ne.jp/review/game/win/{game_id}.json",
        f"https://www.freem.ne.jp/review/game/win/{game_id}?format=json",
        f"https://www.freem.ne.jp/api/review/game/win/{game_id}",
        f"https://www.freem.ne.jp/api/review/game/win/{game_id}.json",
    ]

    for url in candidates:
        try:
            resp = _get(url)
            if resp.status_code != 200:
                continue
            content_type = (resp.headers.get("Content-Type") or "").lower()
            if "json" not in content_type:
                continue
            data = resp.json()
            if isinstance(data, dict) and ("reviews" in data or "data" in data):
                reviews = data.get("reviews") or data.get("data") or []
                if not fetch_all and isinstance(reviews, list):
                    reviews = reviews[:limit]
                return {"url": url, "data": data, "reviews": reviews}
            if isinstance(data, list):
                reviews = data if fetch_all else data[:limit]
                return {"url": url, "data": data, "reviews": reviews}
        except Exception:
            continue
    return None


def fetch_game_title(game_id):
    url = f"https://www.freem.ne.jp/win/game/{game_id}"
    try:
        resp = _get(url)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        og_title = soup.select_one('meta[property="og:title"]')
        if og_title and og_title.get("content"):
            return og_title["content"].strip()
        h1 = soup.select_one("h1")
        if h1:
            text = h1.get_text(" ", strip=True)
            return text if text else None
        title = soup.select_one("title")
        if title:
            text = title.get_text(" ", strip=True)
            return text if text else None
    except Exception:
        return None
    return None


def _parse_review_section(section):
    user = None
    user_el = section.select_one(".review-name")
    if user_el:
        user = user_el.get_text(" ", strip=True) or None

    review_title = None
    title_el = section.select_one(".review-ttl")
    if title_el:
        review_title = title_el.get_text(" ", strip=True) or None

    content = None
    content_el = section.select_one(".review-content p")
    if content_el:
        content = content_el.get_text("\n", strip=True) or None

    like_count = None
    like_el = section.select_one(".review-like-count")
    if like_el:
        like_text = like_el.get_text(" ", strip=True)
        try:
            like_count = int(re.sub(r"[^\d]", "", like_text))
        except Exception:
            like_count = None
    if like_count == 12345:
        like_count = None

    review_no = None
    date = None
    date_el = section.select_one(".review-date")
    if date_el:
        date_text = date_el.get_text(" ", strip=True)
        m = re.search(r"No\.(\d+)\s*-\s*(.+)$", date_text)
        if m:
            review_no = m.group(1)
            date = m.group(2).strip()
        else:
            date = date_text or None

    if not content:
        return None

    return {
        "user": user,
        "date": date,
        "rating": None,
        "status": None,
        "content": content,
        "review_title": review_title,
        "review_no": review_no,
        "like_count": like_count,
    }


def _fetch_reviews_page(game_id, page):
    if page <= 1:
        url = f"https://www.freem.ne.jp/review/game/win/{game_id}"
    else:
        url = f"https://www.freem.ne.jp/review/game/win/{game_id}/page-{page}"
    resp = _get(url)
    if resp.status_code != 200:
        return None, None, url
    soup = BeautifulSoup(resp.text, "html.parser")

    sections = soup.select("section.review-content-wrapper")
    reviews = []
    for sec in sections:
        item = _parse_review_section(sec)
        if item:
            reviews.append(item)

    max_page = 1
    for a in soup.select("ul.pagination a[href]"):
        href = a.get("href") or ""
        m = re.search(r"/page-(\d+)", href)
        if m:
            try:
                max_page = max(max_page, int(m.group(1)))
            except Exception:
                pass

    return reviews, max_page, url


def fetch_reviews_html(game_id, *, limit=20, fetch_all=False, progress_callback=None):
    all_reviews = []
    total_start_time = time.time()
    remaining_limit = limit if not fetch_all else 999999999
    max_page = 1

    page = 1
    while remaining_limit > 0 and page <= max_page:
        start_time = time.time()

        page_reviews, max_page_seen, page_url = _fetch_reviews_page(game_id, page)
        if page_reviews is None:
            break
        max_page = max(max_page, max_page_seen or 1)

        if not page_reviews:
            break

        take = page_reviews if fetch_all else page_reviews[:remaining_limit]
        all_reviews.extend(take)
        fetched_count = len(take)
        remaining_limit -= fetched_count

        elapsed = time.time() - start_time
        total_elapsed = time.time() - total_start_time
        if progress_callback:
            remaining_pages = max(0, max_page - page)
            progress_callback(
                fetched_count=fetched_count,
                elapsed_batch=elapsed,
                remaining=remaining_limit if remaining_limit > 0 else 0,
                total_fetched=len(all_reviews),
                total_elapsed=total_elapsed,
                page=page,
                max_page=max_page,
                page_url=page_url,
                remaining_pages=remaining_pages,
            )

        if remaining_limit <= 0:
            break

        if elapsed < 0.5:
            time.sleep(0.5 - elapsed)
        page += 1

    return all_reviews


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch freem.ne.jp game reviews (comments).")
    parser.add_argument("game_arg", help="Game ID or URL (e.g. https://www.freem.ne.jp/win/game/9869)")
    parser.add_argument("--limit", type=int, default=20, help="Number of reviews to fetch (default: 20)")
    parser.add_argument("--all", action="store_true", help="Fetch all reviews (overrides limit)")
    parser.add_argument("--output", type=str, help="Output file path for JSON (if set, prints progress to stdout)")

    args = parser.parse_args()

    game_id = get_game_id(args.game_arg)
    if not game_id:
        print("Error: Invalid game ID or URL provided.", file=sys.stderr)
        sys.exit(1)

    title = fetch_game_title(game_id)

    api_result = try_fetch_reviews_api(game_id, limit=args.limit, fetch_all=args.all)

    def progress_report(
        *,
        fetched_count,
        elapsed_batch,
        remaining,
        total_fetched,
        total_elapsed,
        page,
        max_page,
        page_url,
        remaining_pages,
    ):
        if total_elapsed > 0:
            avg_speed = total_fetched / total_elapsed
        else:
            avg_speed = 0

        eta_str = "N/A"
        if avg_speed > 0:
            eta_seconds = remaining / avg_speed
            eta_str = f"{eta_seconds:.1f}s" if eta_seconds < 60 else f"{eta_seconds/60:.1f}m"

        msg = (
            f"Fetched {fetched_count} reviews in {elapsed_batch:.2f}s. "
            f"Remaining: {remaining}. Total: {total_fetched} "
            f"(Page: {page}/{max_page}, Speed: {avg_speed:.1f}/s, ETA: {eta_str}) "
            f"[{page_url}]"
        )
        if args.output:
            print(msg)
        else:
            print(msg, file=sys.stderr)

    if api_result is not None:
        reviews_raw = api_result["reviews"]
        comments = []
        if isinstance(reviews_raw, list):
            for item in reviews_raw:
                if isinstance(item, dict):
                    content = item.get("content") or item.get("comment") or item.get("review") or ""
                    content = str(content).strip()
                    if not content:
                        continue
                    comments.append(
                        {
                            "user": item.get("user") or item.get("nickname") or item.get("name"),
                            "date": item.get("date") or item.get("created_at") or item.get("createdAt"),
                            "rating": item.get("rating"),
                            "status": None,
                            "content": content,
                            "review_title": item.get("title"),
                            "review_no": item.get("id") or item.get("no"),
                            "like_count": item.get("like_count") or item.get("likes"),
                        }
                    )
        else:
            comments = []
    else:
        comments = fetch_reviews_html(
            game_id,
            limit=args.limit,
            fetch_all=args.all,
            progress_callback=progress_report,
        )

    output = {
        "source": "freem",
        "game_id": game_id,
        "url": f"https://www.freem.ne.jp/win/game/{game_id}",
        "title": title,
        "rating": {},
        "comments_count": len(comments),
        "comments": comments,
    }

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"Done. Output written to {args.output}")
    else:
        print(json.dumps(output, indent=2, ensure_ascii=False))
