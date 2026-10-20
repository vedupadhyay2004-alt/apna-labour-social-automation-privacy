#!/usr/bin/env python3
"""Publish one queued image or Reel to configured Instagram accounts."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
TIMEZONE = ZoneInfo("Asia/Kolkata")
STATE_PATH = ROOT / ".automation-state.json"
POSTS_PATH = ROOT / "posts.json"
API_VERSION = os.environ.get("META_GRAPH_VERSION", "v25.0")
API_ROOT = f"https://graph.instagram.com/{API_VERSION}"


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def write_state(state: dict) -> None:
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + chr(10), encoding="utf-8")
    temporary.replace(STATE_PATH)


def request_json(url: str, data: dict | None = None) -> dict:
    payload = urlencode(data).encode("utf-8") if data is not None else None
    request = Request(url, data=payload, method="POST" if payload else "GET")
    if payload:
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urlopen(request, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as error:
        # Do not print request URLs: they may contain private account tokens.
        detail = ""
        if isinstance(error, HTTPError):
            try:
                body = json.loads(error.read().decode("utf-8"))
                detail = body.get("error", {}).get("message", "")
            except Exception:
                detail = ""
        raise RuntimeError(detail or f"Meta request failed ({type(error).__name__})") from None
    if "error" in result:
        raise RuntimeError(result["error"].get("message", "Meta API returned an error"))
    return result


def current_slot() -> str:
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        slot = os.environ.get("MANUAL_SLOT", "")
    else:
        cron = os.environ.get("SCHEDULE_CRON", "")
        slot = {"0 9 * * *": "morning", "0 15 * * *": "afternoon"}.get(cron, "")
    if slot not in {"morning", "afternoon"}:
        raise RuntimeError("Could not determine the publishing slot from the workflow event.")
    return slot


def create_container(account_id: str, token: str, post: dict) -> str:
    media_url = post["media_url"]
    media_type = post.get("media_type", "reel").lower()
    fields = {"caption": post.get("caption", ""), "access_token": token}
    if media_type == "image":
        fields["image_url"] = media_url
    elif media_type == "reel":
        fields.update({"video_url": media_url, "media_type": "REELS", "share_to_feed": "true"})
    else:
        raise RuntimeError("media_type must be 'image' or 'reel'.")
    result = request_json(f"{API_ROOT}/{account_id}/media", fields)
    container_id = result.get("id")
    if not container_id:
        raise RuntimeError("Meta did not return a media container ID.")
    return container_id


def wait_until_ready(container_id: str, token: str) -> None:
    deadline = time.time() + 8 * 60
    while time.time() < deadline:
        status = request_json(
            f"{API_ROOT}/{container_id}?{urlencode({'fields': 'status_code,status', 'access_token': token})}"
        )
        code = status.get("status_code")
        if code == "FINISHED":
            return
        if code == "ERROR" or code == "EXPIRED":
            raise RuntimeError(f"Instagram media processing failed ({code}).")
        time.sleep(20)
    raise RuntimeError("Instagram media processing timed out.")


def publish(account_id: str, token: str, post: dict) -> str:
    container_id = create_container(account_id, token, post)
    if post.get("media_type", "reel").lower() == "reel":
        wait_until_ready(container_id, token)
    result = request_json(
        f"{API_ROOT}/{account_id}/media_publish",
        {"creation_id": container_id, "access_token": token},
    )
    media_id = result.get("id")
    if not media_id:
        raise RuntimeError("Instagram did not return a published media ID.")
    return media_id


def main() -> int:
    slot = current_slot()
    posts = read_json(POSTS_PATH)
    queue = posts.get(slot, {}).get("items", [])
    state = read_json(STATE_PATH)
    slot_state = state.setdefault(slot, {"index": 0, "date": None, "completed_accounts": []})
    if not queue:
        print(f"No posts configured for the {slot} slot; nothing was published.")
        return 0

    accounts_text = os.environ.get("IG_ACCOUNTS_JSON", "")
    if not accounts_text:
        raise RuntimeError("Add the IG_ACCOUNTS_JSON repository secret before running this workflow.")
    accounts = json.loads(accounts_text)
    if not isinstance(accounts, list) or not accounts:
        raise RuntimeError("IG_ACCOUNTS_JSON must be a non-empty JSON array.")

    today = datetime.now(TIMEZONE).date().isoformat()
    # Reset partial progress on a new date, while preserving same-day retries.
    if slot_state.get("date") != today:
        slot_state["date"] = today
        slot_state["completed_accounts"] = []
    post = queue[slot_state["index"] % len(queue)]
    if not post.get("media_url", "").startswith("https://"):
        raise RuntimeError("The next queued post needs an HTTPS public media_url.")

    done = set(slot_state.get("completed_accounts", []))
    failures = []
    for account in accounts:
        account_id = str(account.get("id", ""))
        token = account.get("token", "")
        name = account.get("name", account_id)
        if not account_id or not token:
            failures.append(f"An account entry is missing id or token ({name}).")
            continue
        if account_id in done:
            continue
        try:
            publish(account_id, token, post)
            done.add(account_id)
            slot_state["completed_accounts"] = sorted(done)
            write_state(state)
            print(f"Published the {slot} post to account {name}.")
        except Exception as error:
            failures.append(f"Account {name}: {error}")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        raise RuntimeError("Some accounts failed. Successful accounts were recorded so a rerun skips them.")

    slot_state["index"] = (slot_state["index"] + 1) % len(queue)
    slot_state["date"] = None
    slot_state["completed_accounts"] = []
    write_state(state)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
