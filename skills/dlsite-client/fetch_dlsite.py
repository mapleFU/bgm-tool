import argparse
import datetime
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

HEADERS = get_default_headers("dlsite-client")

REQUEST_TIMEOUT_SECONDS = 30
RATE_LIMIT_SECONDS = 0.5

PRODUCT_ID_PATTERN = r"(RJ\d+)"


def _normalize_base_path(base_path):
    base_path = (base_path or "").strip().strip("/")
    if not base_path:
        return "home"
    return base_path


def get_product_id(arg):
    m = re.search(PRODUCT_ID_PATTERN, arg, flags=re.I)
    if m:
        return m.group(1).upper()
    return None


def get_base_path_from_url(arg):
    m = re.search(r"https?://www\.dlsite\.com/([^/]+)/", arg, flags=re.I)
    if m:
        return _normalize_base_path(m.group(1))
    return "home"


def _get_session(cookie):
    s = requests.Session()
    s.headers.update(HEADERS)
    if cookie:
        s.headers["Cookie"] = cookie
    return s


def _get(session, url, *, params=None, timeout=REQUEST_TIMEOUT_SECONDS):
    resp = session.get(url, params=params, timeout=timeout, allow_redirects=True)
    return resp


def fetch_product_html(session, base_path, product_id):
    url = f"https://www.dlsite.com/{base_path}/work/=/product_id/{product_id}.html"
    resp = _get(session, url)
    if resp.status_code != 200:
        return None, url
    resp.encoding = resp.apparent_encoding
    return resp.text, url


def parse_title_from_html(html):
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


def fetch_product_ajax(session, base_path, product_id):
    url = f"https://www.dlsite.com/{base_path}/product/info/ajax"
    resp = _get(session, url, params={"product_id": product_id})
    if resp.status_code != 200:
        return None, url
    try:
        data = resp.json()
    except Exception:
        return None, url
    if isinstance(data, dict) and product_id in data and isinstance(data[product_id], dict):
        return data[product_id], url
    return None, url


def _parse_dlsite_datetime(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
    return s


def fetch_reviews_api_page(session, base_path, product_id, *, limit=20, page=1, order="regist_d", mix_pickup=True):
    url = f"https://www.dlsite.com/{base_path}/api/review"
    params = {
        "product_id": product_id,
        "limit": str(limit),
        "mix_pickup": "true" if mix_pickup else "false",
        "page": str(page),
        "order": order,
        "locale": "ja_JP",
    }
    resp = _get(session, url, params=params)
    if resp.status_code != 200:
        return None, url
    try:
        data = resp.json()
    except Exception:
        return None, url
    return data, url


def fetch_reviews(session, base_path, product_id, *, limit=20, fetch_all=False, progress_callback=None):
    all_reviews = []
    current_page = 1
    remaining_limit = limit if not fetch_all else 999999999
    total_start_time = time.time()
    total_reviews = None

    while remaining_limit > 0:
        start_time = time.time()
        batch_limit = min(remaining_limit, 50)
        data, api_url = fetch_reviews_api_page(
            session,
            base_path,
            product_id,
            limit=batch_limit,
            page=current_page,
            order="regist_d",
            mix_pickup=True,
        )
        if data is None:
            break
        if not isinstance(data, dict) or not data.get("is_success"):
            break

        review_list = data.get("review_list") or []
        if total_reviews is None:
            try:
                total_reviews = int(data.get("review_count") or data.get("reviewCount") or 0)
            except Exception:
                total_reviews = 0

        normalized = []
        for item in review_list:
            if not isinstance(item, dict):
                continue
            content = (item.get("review_text") or "").strip()
            if not content:
                continue
            user = item.get("nick_name") or item.get("reviewer_id") or "Unknown"
            date = _parse_dlsite_datetime(item.get("regist_date") or item.get("entry_date"))
            rate_num = item.get("rate_num") or item.get("rate")
            rating = None
            if rate_num is not None:
                try:
                    rating = int(str(rate_num))
                except Exception:
                    rating = None

            normalized.append(
                {
                    "user": user,
                    "rating": rating,
                    "date": date,
                    "status": item.get("recommend") or item.get("reviewer_status"),
                    "content": content,
                    "review_title": item.get("review_title"),
                    "review_id": item.get("member_review_id"),
                    "spoiler": item.get("spoiler"),
                    "is_purchased": item.get("is_purchased"),
                    "good_review": item.get("good_review"),
                    "bad_review": item.get("bad_review"),
                }
            )

        if not normalized:
            break

        take = normalized if fetch_all else normalized[:remaining_limit]
        all_reviews.extend(take)
        fetched_count = len(take)
        remaining_limit -= fetched_count

        elapsed = time.time() - start_time
        total_elapsed = time.time() - total_start_time
        if progress_callback:
            remaining_est = 0
            if fetch_all and total_reviews is not None and total_reviews > 0:
                remaining_est = max(0, total_reviews - len(all_reviews))
            else:
                remaining_est = max(0, remaining_limit)
            progress_callback(
                fetched_batch=fetched_count,
                elapsed_batch=elapsed,
                remaining=remaining_est,
                total_fetched=len(all_reviews),
                total_elapsed=total_elapsed,
                page=current_page,
                api_url=api_url,
            )

        if fetched_count <= 0:
            break
        if not fetch_all and remaining_limit <= 0:
            break
        if fetch_all and total_reviews is not None and total_reviews > 0 and len(all_reviews) >= total_reviews:
            break

        current_page += 1
        if elapsed < RATE_LIMIT_SECONDS:
            time.sleep(RATE_LIMIT_SECONDS - elapsed)

    return all_reviews, total_reviews


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch DLsite product details and reviews/comments.")
    parser.add_argument("product_arg", help="Product ID or URL (e.g. https://www.dlsite.com/home/work/=/product_id/RJ01164533.html)")
    parser.add_argument("--limit", type=int, default=20, help="Number of reviews to fetch (default: 20)")
    parser.add_argument("--all", action="store_true", help="Fetch all reviews (overrides limit)")
    parser.add_argument("--output", type=str, help="Output file path for JSON (if set, prints progress to stdout)")
    parser.add_argument("--cookie", type=str, default=None, help="Optional Cookie header value (or set DLSITE_COOKIE env var)")

    args = parser.parse_args()

    product_id = get_product_id(args.product_arg)
    if not product_id:
        print("Error: Invalid product ID or URL provided.", file=sys.stderr)
        sys.exit(1)

    base_path = get_base_path_from_url(args.product_arg)
    cookie = args.cookie or os.environ.get("DLSITE_COOKIE")
    session = _get_session(cookie)

    product_html, product_url = fetch_product_html(session, base_path, product_id)
    title = parse_title_from_html(product_html) if product_html else None

    ajax, ajax_url = fetch_product_ajax(session, base_path, product_id)
    if ajax and isinstance(ajax, dict):
        title = title or ajax.get("work_name") or ajax.get("work_name_masked")

    def progress_report(*, fetched_batch, elapsed_batch, remaining, total_fetched, total_elapsed, page, api_url):
        if total_elapsed > 0:
            avg_speed = total_fetched / total_elapsed
        else:
            avg_speed = 0
        eta_str = "N/A"
        if avg_speed > 0:
            eta_seconds = remaining / avg_speed
            eta_str = f"{eta_seconds:.1f}s" if eta_seconds < 60 else f"{eta_seconds/60:.1f}m"
        msg = (
            f"Fetched {fetched_batch} reviews in {elapsed_batch:.2f}s. "
            f"Remaining: {remaining}. Total: {total_fetched} "
            f"(Page: {page}, Speed: {avg_speed:.1f}/s, ETA: {eta_str}) "
            f"[{api_url}]"
        )
        if args.output:
            print(msg)
        else:
            print(msg, file=sys.stderr)

    comments, total_reviews = fetch_reviews(
        session,
        base_path,
        product_id,
        limit=args.limit,
        fetch_all=args.all,
        progress_callback=progress_report,
    )

    rating = {}
    if ajax and isinstance(ajax, dict):
        score = ajax.get("rate_average_2dp")
        rate_count = ajax.get("rate_count")
        review_count = ajax.get("review_count")
        if score is not None:
            rating["score"] = score
        if rate_count is not None:
            rating["count"] = rate_count
        if review_count is not None:
            rating["review_count"] = review_count

    output = {
        "source": "dlsite",
        "product_id": product_id,
        "url": product_url or f"https://www.dlsite.com/{base_path}/work/=/product_id/{product_id}.html",
        "title": title,
        "rating": rating,
        "comments_count": len(comments),
        "comments": comments,
        "meta": {
            "base_path": base_path,
            "ajax_url": ajax_url,
            "reviews_total": total_reviews,
        },
    }

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"Done. Output written to {args.output}")
    else:
        print(json.dumps(output, indent=2, ensure_ascii=False))
