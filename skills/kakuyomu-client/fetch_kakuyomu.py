import argparse
import datetime
import json
import os
import re
import sys
import time
import pathlib

import requests

try:
    from http_common import get_default_headers
except Exception:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from http_common import get_default_headers


HEADERS = get_default_headers("kakuyomu-client")
GRAPHQL_HEADERS = get_default_headers("kakuyomu-client", extra={"Content-Type": "application/json"})
REQUEST_TIMEOUT_SECONDS = 60
RATE_LIMIT_SECONDS = 0.5
MAX_FIRST_PER_REQUEST = 10

WORK_URL_PATTERN = r"/works/(\d+)"
NEXT_DATA_PATTERN = r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>'

GRAPHQL_URL = "https://kakuyomu.jp/graphql"

REVIEWS_QUERY = (
    "query GetWorkReviews($workId: ID!, $first: Int!, $offset: Int, $filter: TextualWorkReviews_Filter, $order: WorkReview_SortOrder) {"
    " work(id: $workId) {"
    "  id"
    "  title"
    "  reviewCount"
    "  totalReviewPoint"
    "  textualWorkReviews(first: $first, offset: $offset, filter: $filter, order: $order) {"
    "   pageInfo { hasNextPage hasPreviousPage }"
    "   nodes {"
    "    id"
    "    title"
    "    body"
    "    point"
    "    likeCount"
    "    isSpoiler"
    "    textualCreatedAt"
    "    reviewerUser { id name activityName }"
    "   }"
    "  }"
    " }"
    "}"
)


def get_work_id(arg):
    m = re.search(WORK_URL_PATTERN, arg)
    if m:
        return m.group(1)
    if arg.isdigit():
        return arg
    return None


def _parse_dt(s):
    if not s:
        return None
    s = str(s).strip()
    try:
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return s


def graphql(session, query, variables, *, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=3):
    payload = {"query": query, "variables": variables}
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = session.post(GRAPHQL_URL, headers=GRAPHQL_HEADERS, data=json.dumps(payload), timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            data = resp.json()
            if "errors" in data and data["errors"]:
                raise RuntimeError(str(data["errors"][0]))
            return data.get("data")
        except Exception as e:
            last_err = e
            if attempt + 1 >= max_retries:
                break
            time.sleep(1.5 * (2**attempt))
    raise last_err


def _normalize_review(it, user):
    body = (it.get("body") or "").strip()
    if not body:
        return None
    return {
        "user": user.get("name") or user.get("activityName") or "Unknown",
        "rating": it.get("point"),
        "date": _parse_dt(it.get("textualCreatedAt")),
        "status": "review",
        "content": body,
        "review_title": it.get("title"),
        "review_id": it.get("id"),
        "spoiler": it.get("isSpoiler"),
        "like_count": it.get("likeCount"),
        "user_id": user.get("id"),
        "user_handle": user.get("activityName"),
    }


def fetch_reviews_from_reviews_page(session, work_id, *, order="created_at_desc"):
    url = f"https://kakuyomu.jp/works/{work_id}/reviews?work_review_order={order}"
    resp = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    m = re.search(NEXT_DATA_PATTERN, resp.text)
    if not m:
        raise RuntimeError("Failed to locate __NEXT_DATA__")
    next_data = json.loads(m.group(1))
    page_props = (next_data.get("props") or {}).get("pageProps") or {}
    apollo = page_props.get("__APOLLO_STATE__") or {}
    work = apollo.get(f"Work:{work_id}") or {}

    title = work.get("title")
    review_count = work.get("reviewCount")
    total_review_point = work.get("totalReviewPoint")

    review_keys = [k for k in work.keys() if k.startswith("textualWorkReviews(")]
    if not review_keys:
        raise RuntimeError("Failed to locate textualWorkReviews in page data")
    conn = work.get(review_keys[0]) or {}
    nodes = conn.get("nodes") or []

    reviews = []
    for ref in nodes:
        review_ref = (ref or {}).get("__ref")
        if not review_ref:
            continue
        it = apollo.get(review_ref) or {}
        user_ref = ((it.get("reviewerUser") or {}).get("__ref")) or None
        user = apollo.get(user_ref) if user_ref else None
        user = user or {}
        normalized = _normalize_review(it, user)
        if normalized:
            reviews.append(normalized)

    return {
        "title": title,
        "review_count": review_count,
        "total_review_point": total_review_point,
        "reviews": reviews,
        "url": url,
    }


def fetch_reviews(session, work_id, *, limit=20, fetch_all=False, batch_size=50, prefer_page=False, progress_callback=None):
    if prefer_page and not fetch_all:
        result = fetch_reviews_from_reviews_page(session, work_id)
        result["reviews"] = (result.get("reviews") or [])[:limit]
        return result

    all_reviews = []
    offset = 0
    total_start_time = time.time()
    total_reviews = None
    total_points = None
    title = None
    has_next = True

    while has_next:
        start_time = time.time()
        first = batch_size if fetch_all else min(batch_size, max(0, limit - len(all_reviews)))
        if first <= 0:
            break

        first = min(int(first), MAX_FIRST_PER_REQUEST)
        data = None
        current_first = first
        while data is None and current_first >= 1:
            try:
                data = graphql(
                    session,
                    REVIEWS_QUERY,
                    {
                        "workId": work_id,
                        "first": int(current_first),
                        "offset": int(offset),
                        "filter": "ALL",
                        "order": "CREATED_AT_DESC",
                    },
                )
            except Exception:
                if not fetch_all and offset == 0:
                    result = fetch_reviews_from_reviews_page(session, work_id)
                    result["reviews"] = (result.get("reviews") or [])[:limit]
                    return result
                if current_first <= 1:
                    raise
                current_first = max(1, current_first // 2)

        work = (data or {}).get("work") or {}
        title = title or work.get("title")
        if total_reviews is None:
            total_reviews = work.get("reviewCount")
        if total_points is None:
            total_points = work.get("totalReviewPoint")

        conn = work.get("textualWorkReviews") or {}
        nodes = conn.get("nodes") or []
        page_info = conn.get("pageInfo") or {}
        has_next = bool(page_info.get("hasNextPage"))

        normalized = []
        for it in nodes:
            if not isinstance(it, dict):
                continue
            user = it.get("reviewerUser") or {}
            normalized_review = _normalize_review(it, user)
            if normalized_review:
                normalized.append(normalized_review)

        if not normalized:
            break

        if fetch_all:
            all_reviews.extend(normalized)
        else:
            need = max(0, limit - len(all_reviews))
            all_reviews.extend(normalized[:need])
            if len(all_reviews) >= limit:
                has_next = False

        offset += len(nodes)

        elapsed = time.time() - start_time
        total_elapsed = time.time() - total_start_time
        if progress_callback:
            if fetch_all and isinstance(total_reviews, int):
                remaining = max(0, total_reviews - len(all_reviews))
            else:
                remaining = max(0, limit - len(all_reviews))
            progress_callback(
                fetched_batch=len(normalized),
                elapsed_batch=elapsed,
                remaining=remaining,
                total_fetched=len(all_reviews),
                total_elapsed=total_elapsed,
                offset=offset,
            )

        if elapsed < RATE_LIMIT_SECONDS:
            time.sleep(RATE_LIMIT_SECONDS - elapsed)

        if not fetch_all and len(all_reviews) >= limit:
            break
        if fetch_all and isinstance(total_reviews, int) and len(all_reviews) >= total_reviews:
            break

    return {
        "title": title,
        "review_count": total_reviews,
        "total_review_point": total_points,
        "reviews": all_reviews,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Kakuyomu work reviews (comments).")
    parser.add_argument("work_arg", help="Work ID or URL (e.g. https://kakuyomu.jp/works/16816927862837735796)")
    parser.add_argument("--limit", type=int, default=20, help="Number of reviews to fetch (default: 20)")
    parser.add_argument("--all", action="store_true", help="Fetch all reviews")
    parser.add_argument("--output", type=str, help="Output file path for JSON (if set, prints progress to stdout)")
    parser.add_argument("--batch-size", type=int, default=10, help="Page size per request (default: 10)")
    parser.add_argument(
        "--prefer-page",
        action="store_true",
        help="Prefer parsing the /reviews page HTML (best-effort, only what the page includes)",
    )

    args = parser.parse_args()

    work_id = get_work_id(args.work_arg)
    if not work_id:
        print("Error: Invalid work ID or URL provided.", file=sys.stderr)
        sys.exit(1)

    work_url = f"https://kakuyomu.jp/works/{work_id}"

    def progress_report(*, fetched_batch, elapsed_batch, remaining, total_fetched, total_elapsed, offset):
        avg_speed = (total_fetched / total_elapsed) if total_elapsed > 0 else 0
        eta_str = "N/A"
        if avg_speed > 0:
            eta_seconds = remaining / avg_speed
            eta_str = f"{eta_seconds:.1f}s" if eta_seconds < 60 else f"{eta_seconds/60:.1f}m"
        msg = (
            f"Fetched {fetched_batch} reviews in {elapsed_batch:.2f}s. "
            f"Remaining: {remaining}. Total: {total_fetched} "
            f"(Offset: {offset}, Speed: {avg_speed:.1f}/s, ETA: {eta_str})"
        )
        if args.output:
            print(msg)
        else:
            print(msg, file=sys.stderr)

    session = requests.Session()

    result = fetch_reviews(
        session,
        work_id,
        limit=args.limit,
        fetch_all=args.all,
        batch_size=args.batch_size,
        prefer_page=args.prefer_page,
        progress_callback=progress_report,
    )

    title = result.get("title")
    review_count = result.get("review_count")
    total_review_point = result.get("total_review_point")
    reviews = result.get("reviews") or []

    rating = {}
    if isinstance(review_count, int):
        rating["count"] = review_count
    if isinstance(total_review_point, int):
        rating["total_points"] = total_review_point
        if isinstance(review_count, int) and review_count > 0:
            rating["score"] = round(total_review_point / review_count, 4)

    output = {
        "source": "kakuyomu",
        "work_id": work_id,
        "url": work_url,
        "title": title,
        "rating": rating,
        "comments_count": len(reviews),
        "comments": reviews,
    }

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"Done. Output written to {args.output}")
    else:
        print(json.dumps(output, indent=2, ensure_ascii=False))
