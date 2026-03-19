import os


DEFAULT_USER_AGENT = "bgm-exp/1.0"


def get_user_agent(component=None):
    base = (os.environ.get("BGMEXP_USER_AGENT") or os.environ.get("USER_AGENT") or DEFAULT_USER_AGENT).strip()
    if component:
        return f"{base} ({component})"
    return base


def get_default_headers(component=None, extra=None):
    headers = {
        "User-Agent": get_user_agent(component),
    }
    if extra:
        headers.update(extra)
    return headers

