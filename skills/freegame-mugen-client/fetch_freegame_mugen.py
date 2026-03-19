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

HEADERS = get_default_headers("freegame-mugen-client")

REQUEST_TIMEOUT_SECONDS = 30
RATE_LIMIT_SECONDS = 0.5

GAME_URL_PATTERN = r"/game_(\d+)\.html"


def get_game_id(arg):
    m = re.search(GAME_URL_PATTERN, arg)
    if m:
        return m.group(1)
    if arg.isdigit():
        return arg
    return None


def _get(url, *, timeout=REQUEST_TIMEOUT_SECONDS):
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.encoding = resp.apparent_encoding
    return resp


def fetch_game_page(game_id):
    url = f"https://freegame-mugen.jp/roleplaying/game_{game_id}.html"
    resp = _get(url)
    if resp.status_code != 200:
        return None, url
    return resp.text, url


def parse_title_from_game_page(html):
    soup = BeautifulSoup(html, "html.parser")
    og = soup.select_one('meta[property="og:title"]')
    if og and og.get("content"):
        return og["content"].strip()
    if soup.title:
        t = soup.title.get_text(" ", strip=True)
        return t if t else None
    h1 = soup.select_one("h1")
    if h1:
        t = h1.get_text(" ", strip=True)
        return t if t else None
    return None


def _parse_byline(byline_el):
    if not byline_el:
        return None, None
    parts = []
    for s in byline_el.stripped_strings:
        s = s.strip()
        if not s or s == "|" or s == "返信":
            continue
        parts.append(s)
    date = None
    date_re = re.compile(r"\d{4}年\d{1,2}月\d{1,2}日")
    for p in parts:
        if date_re.search(p):
            date = p
            break

    user = parts[0] if len(parts) >= 1 else None
    if user and user.endswith("から") and len(user) > 2:
        user = user[:-2].strip() or user

    if date is None:
        date = parts[1] if len(parts) >= 2 else None
    return user, date


def _parse_rating(li):
    el = li.select_one(".mtCommentRating")
    if not el:
        return None
    title = el.get("title")
    if title and str(title).isdigit():
        return int(title)
    classes = el.get("class") or []
    for c in classes:
        m = re.match(r"star_(\d+)$", str(c))
        if m:
            return int(m.group(1))
    inner = el.get_text(" ", strip=True)
    if inner.isdigit():
        return int(inner)
    return None


def _parse_subscores(li):
    subs = {}
    for key in ["story", "grafic", "music", "system", "original"]:
        el = li.select_one(f"li.{key} span.num")
        if not el:
            continue
        val = el.get_text(" ", strip=True)
        try:
            subs[key] = int(val)
        except Exception:
            continue
    return subs or None


def _parse_content(li):
    spoiler = li.select_one(".spoiler-content")
    if spoiler:
        text = spoiler.get_text("\n", strip=True)
        return text if text else None
    comment = li.select_one("div.comment")
    if comment:
        text = comment.get_text("\n", strip=True)
        text = text.replace("ネタバレ表示する", "").strip()
        return text if text else None
    return None


def parse_comments_fragment(html_fragment):
    soup = BeautifulSoup(html_fragment, "html.parser")
    items = []
    for li in soup.select("li"):
        div = li.select_one("div[id^=comment-]")
        comment_id = None
        if div and div.get("id"):
            m = re.match(r"comment-(\d+)$", div["id"])
            if m:
                comment_id = m.group(1)

        byline = li.select_one(".byline")
        user, date = _parse_byline(byline)
        rating = _parse_rating(li)
        content = _parse_content(li)
        if not content:
            continue

        li_classes = li.get("class") or []
        comment_type = "review" if "impr" in li_classes else ("chat" if "chat" in li_classes else None)
        subscores = _parse_subscores(li)

        items.append(
            {
                "user": user,
                "date": date,
                "rating": rating,
                "status": comment_type,
                "content": content,
                "comment_id": comment_id,
                "subscores": subscores,
            }
        )
    return items


def parse_comments_from_game_page(html):
    soup = BeautifulSoup(html, "html.parser")
    ul = soup.select_one("ul#comments-content.comments-content")
    if not ul:
        return []
    return parse_comments_fragment(str(ul))


def fetch_more_comments_fragment(game_id):
    url = f"https://freegame-mugen.jp/roleplaying/comment_{game_id}.html"
    resp = _get(url)
    if resp.status_code != 200:
        return None, url
    return resp.text, url


def fetch_comments(game_id, *, game_html=None, game_url=None, limit=20, fetch_all=False, progress_callback=None):
    if game_html is None or game_url is None:
        game_html, game_url = fetch_game_page(game_id)
        if game_html is None:
            return None, game_url

    all_items = parse_comments_from_game_page(game_html)
    seen = set()
    deduped = []
    for it in all_items:
        key = it.get("comment_id") or (it.get("user"), it.get("date"), it.get("content"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    all_items = deduped

    if progress_callback:
        progress_callback(fetched=len(all_items), source="game_page", url=game_url)

    need_more = fetch_all or (limit is not None and len(all_items) < limit)
    if need_more:
        start_time = time.time()
        more_html, more_url = fetch_more_comments_fragment(game_id)
        if more_html is not None:
            more_items = parse_comments_fragment(more_html)
            for it in more_items:
                key = it.get("comment_id") or (it.get("user"), it.get("date"), it.get("content"))
                if key in seen:
                    continue
                seen.add(key)
                all_items.append(it)
            if progress_callback:
                progress_callback(fetched=len(more_items), source="comment_fragment", url=more_url)
        elapsed = time.time() - start_time
        if elapsed < RATE_LIMIT_SECONDS:
            time.sleep(RATE_LIMIT_SECONDS - elapsed)

    if not fetch_all and limit is not None:
        all_items = all_items[:limit]

    return all_items, game_url


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch freegame-mugen.jp game comments/reviews.")
    parser.add_argument("game_arg", help="Game ID or URL (e.g. https://freegame-mugen.jp/roleplaying/game_13132.html)")
    parser.add_argument("--limit", type=int, default=20, help="Number of comments to fetch (default: 20)")
    parser.add_argument("--all", action="store_true", help="Fetch all comments (overrides limit)")
    parser.add_argument("--output", type=str, help="Output file path for JSON (if set, prints progress to stdout)")

    args = parser.parse_args()

    game_id = get_game_id(args.game_arg)
    if not game_id:
        print("Error: Invalid game ID or URL provided.", file=sys.stderr)
        sys.exit(1)

    game_html, game_url = fetch_game_page(game_id)
    if game_html is None:
        print(f"Error: Failed to fetch game page: {game_url}", file=sys.stderr)
        sys.exit(1)

    title = parse_title_from_game_page(game_html)

    def progress_report(*, fetched, source, url):
        msg = f"Fetched {fetched} items from {source}: {url}"
        if args.output:
            print(msg)
        else:
            print(msg, file=sys.stderr)

    comments, _ = fetch_comments(
        game_id,
        game_html=game_html,
        game_url=game_url,
        limit=args.limit,
        fetch_all=args.all,
        progress_callback=progress_report,
    )
    if comments is None:
        print("Error: Failed to fetch comments.", file=sys.stderr)
        sys.exit(1)

    output = {
        "source": "freegame-mugen",
        "game_id": game_id,
        "url": game_url,
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
