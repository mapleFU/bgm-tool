import sys
import requests
import re
import json
import datetime
import argparse
import os

import time
import pathlib

# Configuration
DEFAULT_TOKEN = None # No hardcoded token
try:
    from http_common import get_default_headers
except Exception:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from http_common import get_default_headers

HEADERS = get_default_headers("bangumi-client")
BASE_URL = "https://api.bgm.tv/v0"
SUBJECT_URL_PATTERN = r"subject/(\d+)"

def get_headers(token=None):
    headers = HEADERS.copy()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

def get_subject_id(arg):
    # Check if arg is a url
    m = re.search(SUBJECT_URL_PATTERN, arg)
    if m:
        return m.group(1)
    # Assume it's an ID if it's digits
    if arg.isdigit():
        return arg
    return None

def fetch_subject_details(subject_id, token=None):
    url = f"{BASE_URL}/subjects/{subject_id}"
    try:
        response = requests.get(url, headers=get_headers(token))
        if response.status_code == 200:
            data = response.json()
            return {
                "title": data.get("name"),
                "rating": data.get("rating", {}),
                "summary": data.get("summary"),
                "tags": data.get("tags", [])
            }
        return None
    except Exception as e:
        # print(f"Error fetching details: {e}", file=sys.stderr)
        return None

def _fetch_comments_private_api_page(subject_id, limit=20, offset=0, token=None):
    """
    Try to fetch comments from Private API (next.bgm.tv)
    Endpoint: https://next.bgm.tv/p1/subjects/{subject_id}/comments
    Supports pagination via limit and offset.
    Returns: (comments_list, total_count) or (None, 0) on failure
    """
    url = f"https://next.bgm.tv/p1/subjects/{subject_id}/comments"
    params = {
        "limit": limit,
        "offset": offset
    }
    try:
        # Private API usually needs cookie auth, but some endpoints might be public or accessible
        # We try with the same headers, but it might fail or return empty if not authenticated properly.
        # Based on curl test, it seems accessible with User-Agent.
        response = requests.get(url, headers=get_headers(token), params=params)
        if response.status_code != 200:
            return None, 0
            
        data = response.json()
        total_count = data.get('total', 0)
        
        if isinstance(data, dict) and 'data' in data:
            data_list = data['data']
        elif isinstance(data, list):
            data_list = data
        else:
            return None, 0
                
        comments = []
        for item in data_list:
            # Structure check
            if 'user' not in item:
                continue
                
            user_obj = item.get('user', {})
            user = user_obj.get('nickname', user_obj.get('username', 'Unknown'))
            content = item.get('comment', '')
            if not content:
                 continue

            rating = item.get('rate', 0)
            if rating == 0:
                rating = None
            
            # Timestamp to date string
            updated_at = item.get('updatedAt')
            date_str = ""
            if updated_at:
                try:
                    dt = datetime.datetime.fromtimestamp(updated_at)
                    date_str = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    pass

            # Status mapping (Private API 'type' field?)
            # type: 1=wish, 2=collect, 3=do, 4=on_hold, 5=dropped
            status_map = {
                1: "想读", # or 想看/想玩 depending on subject type, simplified here
                2: "读过", # or 看过/玩过
                3: "在读",
                4: "搁置",
                5: "抛弃"
            }
            status_type = item.get('type')
            status = status_map.get(status_type, "")

            comments.append({
                "user": user,
                "rating": rating,
                "date": date_str,
                "status": status,
                "content": content
            })
            
        return comments, total_count
    except Exception as e:
        # print(f"Error fetching from private API: {e}", file=sys.stderr)
        return None, 0

def fetch_comments_private_api(subject_id, limit=20, offset=0, token=None, fetch_all=False, progress_callback=None):
    all_comments = []
    current_offset = offset
    
    # If fetch_all is True, limit is ignored initially, we fetch everything
    remaining_limit = limit if not fetch_all else 999999999
    
    first_batch = True
    total_start_time = time.time()
    
    while remaining_limit > 0:
        start_time = time.time()
        
        # Private API has a limit of 99 per request usually, let's use 50 to be safe/standard
        batch_limit = min(remaining_limit, 99)
        
        comments, total_count = _fetch_comments_private_api_page(subject_id, batch_limit, current_offset, token=token)
        
        if comments is None:
            # If fetch fails
            if not all_comments:
                return None
            break
            
        if not comments:
            break
            
        all_comments.extend(comments)
        fetched_count = len(comments)
        
        # Update remaining limit logic
        if fetch_all and first_batch:
            # Update remaining_limit based on total count
            # Calculate how many more we need
            # Total - what we started at (offset) - what we just got
            remaining_needed = total_count - offset - fetched_count
            remaining_limit = remaining_needed
            first_batch = False
        else:
            remaining_limit -= fetched_count
            
        current_offset += fetched_count
        
        elapsed = time.time() - start_time
        total_elapsed = time.time() - total_start_time

        if progress_callback:
            progress_callback(fetched_count, elapsed, remaining_limit if remaining_limit > 0 else 0, len(all_comments), total_elapsed)

        # If we got fewer than requested (and not because we hit the end of total), break
        # But relying on total_count is better for fetch_all
        if not fetch_all and fetched_count < batch_limit:
             break
             
        if remaining_limit <= 0:
            break
            
        # Rate limiting: Ensure at least 0.5s between requests
        if elapsed < 0.5:
            time.sleep(0.5 - elapsed)
        
    return all_comments

def fetch_comments(subject_id, limit=20, offset=0, token=None, fetch_all=False, progress_callback=None):
    # Only use Private API (next.bgm.tv)
    # The scraping logic has been removed as per user request.
    comments = fetch_comments_private_api(subject_id, limit=limit, offset=offset, token=token, fetch_all=fetch_all, progress_callback=progress_callback)
    return comments if comments is not None else []

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Bangumi subject details and comments.")
    parser.add_argument("subject_arg", help="Subject ID or URL")
    parser.add_argument("--limit", type=int, default=20, help="Number of comments to fetch (default: 20)")
    parser.add_argument("--offset", type=int, default=0, help="Offset for comments (default: 0)")
    parser.add_argument("--all", action="store_true", help="Fetch all comments (overrides limit)")
    parser.add_argument("--output", type=str, help="Output file path for JSON (if set, prints progress to stdout)")
    parser.add_argument("--token", type=str, default=None, help="Bangumi API Token (optional, can also be set via BANGUMI_TOKEN env var)")
    
    args = parser.parse_args()
    
    token = args.token or os.environ.get("BANGUMI_TOKEN")

    subject_id = get_subject_id(args.subject_arg)
    
    if not subject_id:
        print("Error: Invalid subject ID or URL provided.", file=sys.stderr)
        sys.exit(1)

    # Fetch details
    details = fetch_subject_details(subject_id, token=token)
    if not details:
         # Fallback to minimal info if details fetch fails
         details = {"subject_id": subject_id}
    else:
         details["subject_id"] = subject_id

    # Progress callback
    def progress_report(fetched_batch, elapsed_batch, remaining, total_fetched, total_elapsed):
        # Calculate speed based on total progress
        if total_elapsed > 0:
            avg_speed = total_fetched / total_elapsed
        else:
            avg_speed = 0
            
        if avg_speed > 0:
            eta_seconds = remaining / avg_speed
            if eta_seconds < 60:
                eta_str = f"{eta_seconds:.1f}s"
            else:
                eta_str = f"{eta_seconds/60:.1f}m"
        else:
            eta_str = "N/A"
            
        msg = f"Fetched {fetched_batch} comments in {elapsed_batch:.2f}s. Remaining: {remaining}. Total: {total_fetched} (Speed: {avg_speed:.1f}/s, ETA: {eta_str})"
        
        if args.output:
            print(msg)
        else:
             print(msg, file=sys.stderr)

    # Fetch comments
    comments = fetch_comments(subject_id, limit=args.limit, offset=args.offset, token=token, fetch_all=args.all, progress_callback=progress_report)
    
    output = {
        "subject_id": subject_id,
        "title": details.get("title"),
        "rating": details.get("rating"),
        "comments_count": len(comments) if comments else 0,
        "comments": comments
    }

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"Done. Output written to {args.output}")
    else:
        print(json.dumps(output, indent=2, ensure_ascii=False))
