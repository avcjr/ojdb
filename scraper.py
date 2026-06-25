"""
OnlineJobs.ph -> Discord notifier

Fetches the latest job postings from onlinejobs.ph/jobseekers/jobsearch,
figures out which ones are new since the last run, and posts them to a
Discord channel via webhook.

Each notification includes:
  - Job title
  - Date & time posted
  - Job's number for that day (resets at midnight Philippine time)

State (which jobs we've already seen, and today's running counter) is
stored in state.json, which the GitHub Actions workflow commits back to
the repo after every run.
"""

import json
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

JOB_SEARCH_URL = "https://www.onlinejobs.ph/jobseekers/jobsearch"
STATE_FILE = "state.json"
PH_TZ = ZoneInfo("Asia/Manila")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Matches job links like:
# /jobseekers/job/Senior-Property-Accounting-Manager-Real-Estate-Controller-1675735
JOB_LINK_RE = re.compile(r"^/jobseekers/job/([\w\-]+)-(\d+)$")

# Matches "Posted on 2026-06-24 22:57:44" anywhere in a listing's text
POSTED_RE = re.compile(r"Posted on\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})")


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"seen_ids": [], "day": None, "counter": 0}
    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save_state(state):
    # Cap seen_ids so the file doesn't grow forever (keep the most recent 2000)
    state["seen_ids"] = state["seen_ids"][-2000:]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch_jobs_page():
    resp = requests.get(JOB_SEARCH_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_jobs(html):
    """
    Returns a list of dicts (most-recent-first, matching the page order):
      { "id": "1675735", "title": "...", "url": "...", "posted_at": datetime }
    """
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen_ids_on_page = set()

    for a in soup.find_all("a", href=True):
        m = JOB_LINK_RE.match(a["href"])
        if not m:
            continue
        job_id = m.group(2)
        if job_id in seen_ids_on_page:
            continue  # each job appears in multiple <a> tags on the page

        # Walk up to the parent block that contains the "Posted on ..." text
        block = a
        posted_text = None
        title_text = a.get_text(strip=True)
        for _ in range(6):  # climb a few levels looking for context
            if block.parent is None:
                break
            block = block.parent
            text = block.get_text(" ", strip=True)
            pm = POSTED_RE.search(text)
            if pm:
                posted_text = pm.group(1)
                # Title is usually the text before "Full Time"/"Part Time"/"Gig"
                title_match = re.split(
                    r"\s+(Full Time|Part Time|Gig)\s+\*Posted", text
                )
                if title_match:
                    title_text = title_match[0].strip()
                break

        if not posted_text:
            continue  # couldn't find a date for this one, skip it

        seen_ids_on_page.add(job_id)
        try:
            posted_dt = datetime.strptime(posted_text, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=PH_TZ
            )
        except ValueError:
            continue

        jobs.append(
            {
                "id": job_id,
                "title": title_text,
                "url": f"https://www.onlinejobs.ph{a['href']}",
                "posted_at": posted_dt,
            }
        )

    return jobs


def send_discord_notification(job, day_number):
    posted_str = job["posted_at"].strftime("%Y-%m-%d %I:%M %p")
    embed = {
        "title": job["title"],
        "url": job["url"],
        "color": 0x2ECC71,
        "fields": [
            {"name": "Posted", "value": posted_str, "inline": True},
            {
                "name": "Job # today",
                "value": f"#{day_number}",
                "inline": True,
            },
        ],
        "footer": {"text": "OnlineJobs.ph new listing"},
    }
    payload = {"embeds": [embed]}
    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    resp.raise_for_status()


def send_discord_alert(message):
    """Used to report scraper errors / structural breakage to Discord."""
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": f":warning: **OJ Bot alert:** {message}"},
            timeout=15,
        )
    except requests.RequestException:
        pass


def main():
    if not DISCORD_WEBHOOK_URL:
        print("ERROR: DISCORD_WEBHOOK_URL environment variable not set.", file=sys.stderr)
        sys.exit(1)

    state = load_state()
    is_first_run = state.get("day") is None and not state.get("seen_ids")
    seen_ids = set(state.get("seen_ids", []))
    today_str = datetime.now(PH_TZ).strftime("%Y-%m-%d")

    # Reset the daily counter if it's a new day (Philippine time)
    if state.get("day") != today_str:
        state["day"] = today_str
        state["counter"] = 0

    try:
        html = fetch_jobs_page()
    except requests.RequestException as e:
        send_discord_alert(f"Failed to fetch the jobs page: {e}")
        sys.exit(1)

    jobs = parse_jobs(html)

    if not jobs:
        send_discord_alert(
            "Parsed 0 jobs from the page. OnlineJobs.ph may have changed its "
            "page structure \u2014 the scraper needs a look."
        )
        sys.exit(1)

    # Page is newest-first; reverse so we post in chronological order
    jobs_oldest_first = list(reversed(jobs))

    if is_first_run:
        # Don't blast every currently-listed job to Discord on first run.
        # Just record what's there now as the baseline.
        state["seen_ids"] = [j["id"] for j in jobs_oldest_first]
        save_state(state)
        send_discord_alert(
            f"Bot started up. Recorded {len(jobs_oldest_first)} existing jobs "
            "as a baseline \u2014 you'll get notified starting with the next new posting."
        )
        print(f"First run: seeded {len(jobs_oldest_first)} jobs, no notifications sent.")
        return

    new_jobs = [j for j in jobs_oldest_first if j["id"] not in seen_ids]

    if not new_jobs:
        print("No new jobs found.")
        save_state(state)
        return

    for job in new_jobs:
        state["counter"] += 1
        try:
            send_discord_notification(job, state["counter"])
            print(f"Notified: #{state['counter']} {job['title']} ({job['id']})")
        except requests.RequestException as e:
            print(f"Failed to send Discord notification for {job['id']}: {e}", file=sys.stderr)
            # Don't count this job as "counted" if the notification failed,
            # but do mark it as seen so we don't get stuck retrying forever.
        seen_ids.add(job["id"])

    state["seen_ids"] = list(seen_ids)
    save_state(state)


if __name__ == "__main__":
    main()
