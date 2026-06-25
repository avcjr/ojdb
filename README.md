# OnlineJobs.ph → Discord Notifier

Checks [onlinejobs.ph/jobseekers/jobsearch](https://www.onlinejobs.ph/jobseekers/jobsearch)
every 5 minutes and posts a Discord message for every new job listing, with:

- **Job title**
- **Date & time posted**
- **Job # for the day** (resets at midnight Philippine time)

100% free to run: GitHub Actions (free tier) + a Discord webhook (free).

---

## Setup (one-time, ~10 minutes)

### 1. Create a Discord webhook

1. In Discord, go to the channel you want notifications in.
2. Click the gear icon (Edit Channel) → **Integrations** → **Webhooks** → **New Webhook**.
3. Name it (e.g. "OJ Job Alerts"), then click **Copy Webhook URL**. Keep this handy — you'll need it in step 3.

### 2. Create a GitHub repo

1. Go to [github.com/new](https://github.com/new).
2. Name it something like `oj-discord-bot`. It can be **private** — Actions still works on private repos, just with a 2,000 min/month free quota (this script uses only a few minutes per day, so you're nowhere near that limit).
3. Upload all the files from this project to the repo (or `git push` them — see below).

### 3. Add your webhook URL as a GitHub Secret

1. In your repo, go to **Settings → Secrets and variables → Actions**.
2. Click **New repository secret**.
3. Name: `DISCORD_WEBHOOK_URL`
4. Value: paste the webhook URL you copied in step 1.
5. Save.

This keeps your webhook URL out of the code, so it's safe even in a public repo.

### 4. Push the files

From this project folder:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/oj-discord-bot.git
git push -u origin main
```

### 5. Enable Actions (if needed) and do a test run

1. Go to your repo's **Actions** tab.
2. You should see the "Check OnlineJobs.ph for new postings" workflow.
3. Click it, then **Run workflow** (the manual trigger button) to test it immediately rather than waiting 5 minutes.
4. Check the run logs. The **first run** will *not* post any jobs to Discord — it just records what's currently on the page as a baseline, and sends one heads-up message to confirm it started. Every run after that will notify on genuinely new postings.

That's it. From here it runs itself every 5 minutes for free.

---

## How it works

- `scraper.py` fetches the job search page, parses out each listing's ID, title, and posted timestamp.
- `state.json` keeps track of which job IDs have already been notified, plus the day's running counter. The GitHub Action commits this file back to the repo after every run, so state persists between runs.
- The daily counter resets automatically at midnight **Philippine time** (Asia/Manila), regardless of what time zone the GitHub Actions server runs in.
- If the scraper ever parses 0 jobs (e.g. onlinejobs.ph changes their page layout) or fails to fetch the page, it posts a warning message to your Discord channel so you know to check on it.

## Adjusting the check frequency

Edit `.github/workflows/check-jobs.yml`, the line:

```yaml
- cron: "*/5 * * * *"
```

`*/5` means "every 5 minutes." You could change it to `*/15` for every 15 minutes, etc. GitHub's free tier doesn't reliably support intervals under 5 minutes.

## Troubleshooting

- **No notifications ever arrive:** Check the Actions tab for failed runs and read the logs. Common causes: missing/incorrect `DISCORD_WEBHOOK_URL` secret, or onlinejobs.ph temporarily blocking the request (rare, but possible — sites sometimes rate-limit or challenge automated traffic).
- **Getting a "0 jobs parsed" warning:** onlinejobs.ph likely changed their HTML structure. Ping me (or open an issue) and the parsing logic in `scraper.py` will need a small update.
- **Want to filter by keyword later:** this version notifies on *every* new job. Filtering can be added later as a simple keyword check before `send_discord_notification` is called.
