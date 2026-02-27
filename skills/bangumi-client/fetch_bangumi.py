import sys
import requests
import re
import json
import datetime
import argparse
import os

# Configuration
DEFAULT_TOKEN = None # No hardcoded token
HEADERS = {
    "User-Agent": "Trae/1.0 (bangumi-client)"
}
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
            return None
            
        data = response.json()
        if isinstance(data, dict) and 'data' in data:
            data_list = data['data']
        elif isinstance(data, list):
            data_list = data
        else:
            return None
                
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
            
        return comments
    except Exception as e:
        # print(f"Error fetching from private API: {e}", file=sys.stderr)
        return None

def fetch_comments_private_api(subject_id, limit=20, offset=0, token=None):
    all_comments = []
    current_offset = offset
    remaining_limit = limit
    
    while remaining_limit > 0:
        # Private API has a limit of 99 per request
        batch_limit = min(remaining_limit, 99)
        comments = _fetch_comments_private_api_page(subject_id, batch_limit, current_offset, token=token)
        
        if comments is None:
            # If first page fails, return None to trigger fallback
            if not all_comments:
                return None
            break
            
        if not comments:
            break
            
        all_comments.extend(comments)
        
        if len(comments) < batch_limit:
            # Fewer comments returned than requested, meaning we reached the end
            break
            
        remaining_limit -= len(comments)
        current_offset += len(comments)
        
    return all_comments

def fetch_comments(subject_id, limit=20, offset=0, token=None):
    # Only use Private API (next.bgm.tv)
    # The scraping logic has been removed as per user request.
    comments = fetch_comments_private_api(subject_id, limit=limit, offset=offset, token=token)
    return comments if comments is not None else []

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Bangumi subject details and comments.")
    parser.add_argument("subject_arg", help="Subject ID or URL")
    parser.add_argument("--limit", type=int, default=20, help="Number of comments to fetch (default: 20)")
    parser.add_argument("--offset", type=int, default=0, help="Offset for comments (default: 0)")
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

    # Fetch comments
    comments = fetch_comments(subject_id, limit=args.limit, offset=args.offset, token=token)
    
    output = {
        "subject_id": subject_id,
        "title": details.get("title"),
        "rating": details.get("rating"),
        "comments_count": len(comments) if comments else 0,
        "comments": comments
    }

    print(json.dumps(output, indent=2, ensure_ascii=False))
