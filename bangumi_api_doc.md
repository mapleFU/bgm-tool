# Bangumi API Documentation

This document records the available Bangumi APIs and methods to retrieve subject information.

## 1. Public API (v0)

The modern API is located at `https://api.bgm.tv/v0`. It requires an Access Token for authenticated requests.

- **Base URL**: `https://api.bgm.tv/v0`
- **Authentication**: Header `Authorization: Bearer <your_access_token>`
- **User-Agent**: Custom User-Agent is required (e.g., `MyApp/1.0`).

### Get Subject Details
Retrieves subject metadata, including rating and total count.

- **Endpoint**: `GET /subjects/{subject_id}`
- **Example**: `https://api.bgm.tv/v0/subjects/127832`
- **Response Fields**:
  - `rating.score`: Average score (e.g., 7.7)
  - `rating.total`: Total number of ratings (e.g., 55)
  - `rating.count`: Distribution of ratings (1-10)

## 2. Legacy API

The older API endpoint structure. Still functional for some data.

- **Endpoint**: `GET https://api.bgm.tv/subject/{subject_id}?responseGroup=large`
- **Note**: Does not reliably return short comments (tags/tucao) even with `responseGroup=large`.

## 3. Retrieving Comments (Short Comments / 吐槽)

The public API does not currently provide a direct endpoint to fetch the short comments displayed on the subject page (the "吐槽箱" or "Comments Box").

### Workaround: HTML Scraping
To get the short comments, we must scrape the subject page directly.

- **URL**: `https://bgm.tv/subject/{subject_id}`
- **Method**: HTTP GET
- **Target Element**: `<div id="comment_box">` contains the list of comments.
- **Structure**: Each comment is within `<div class="item">`.
  - User: `.text > a` (username)
  - Content: `.text` (comment text)
  - Rating: `.starsinfo` (class indicates rating, e.g., `sstars7` = 7/10)

## 4. Private API

The Private API (`server-private`) is used by the new frontend but is not stable for external use. It requires cookie-based authentication and does not support CORS.
- **Repository**: `https://github.com/bangumi/server-private`
- **Recommendation**: Avoid unless necessary; stick to Public API + Scraping for stability.
