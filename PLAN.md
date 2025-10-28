Here’s a focused build plan in Markdown for your `eyes-and-ears` repo. You can drop this in as `PLAN.md` and hand it to an AI cursor/agent to execute step by step.

````markdown
# eyes-and-ears — Public Repo Watchdog

Goal:  
Monitor a list of GitHub repositories that are expected to become public in the future.  
Alert in Slack (one time per repo) the moment each repo becomes publicly accessible.  
Run on GitHub Actions every 5 minutes.  
Persist alert state in the repo itself so we don't spam Slack.

---

## 0. Repo bootstrap

Create a new GitHub repo called `eyes-and-ears` with the following initial files:

- `watcher.py` (Python script that does polling + alerting + state update + git push)
- `config.json` (list of repos to watch)
- `state.json` (per-repo state: whether we've already alerted)
- `.github/workflows/watch-public.yml` (GitHub Actions workflow)
- `PLAN.md` (this file)

Also set up 2 GitHub Actions secrets in this repo:
- `SLACK_WEBHOOK_URL`
- `GH_PAT`

Details in sections below.

---

## 1. Monitoring logic

### 1.1 What we are detecting

For each target repo `owner/name`:
- Call `GET https://api.github.com/repos/owner/name`.
- If GitHub returns:
  - `200 OK` and JSON has `"private": false` → repo is now public.
  - `404 Not Found` → either doesn't exist yet or is private and we don't have access. Treat this as "not public yet".
  - Anything else (403 rate limit, 5xx) → treat as "not public yet" and log to stderr.

We only alert the **first** time a repo is confirmed public. After alerting once, we never alert again for that repo.

### 1.2 State tracking

We track alerts in `state.json`, structured like:

```json
{
  "facebookresearch/sam3": { "alert_sent": true },
  "openai/some-new-model": { "alert_sent": false }
}
````

Rules:

* Every repo in `config.json` *must* have an entry in `state.json`.
* `"alert_sent": false` means "we're still waiting to alert".
* `"alert_sent": true` means "we already alerted Slack at least once in the past".

After each run, `state.json` is updated and committed back to `main`.
That commit is what prevents duplicate Slack alerts in future runs.

---

## 2. Files to create

### 2.1 `config.json`

Human-maintained list of repos we are watching.

Create this file:

```json
{
  "repos": [
    "facebookresearch/sam3"
  ]
}
```

Rules:

* Each entry is `"<owner>/<repo>"`.
* To add more repos later, just edit this file and commit. No code changes needed.

### 2.2 `state.json`

Internal state for alerting. Start with an empty object:

```json
{}
```

Do not manually flip `alert_sent` to `true` unless you're intentionally suppressing alerts.

### 2.3 `watcher.py`

Create this file with the following content:

```python
import os
import json
import requests
import sys
from pathlib import Path
import subprocess
import copy

CONFIG_FILE = Path("config.json")
STATE_FILE = Path("state.json")

SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
GITHUB_API_TOKEN = os.environ.get("GITHUB_API_TOKEN")  # optional but recommended

def load_config():
    with CONFIG_FILE.open() as f:
        data = json.load(f)
    # normalize + dedupe
    repos = list(dict.fromkeys([r.strip() for r in data.get("repos", []) if r.strip()]))
    return repos

def load_state():
    if not STATE_FILE.exists():
        return {}
    with STATE_FILE.open() as f:
        return json.load(f)

def save_state(state):
    with STATE_FILE.open("w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")

def get_repo_status(full_name):
    """
    full_name: 'owner/repo'
    returns: (exists_and_visible, is_public)
    """
    url = f"https://api.github.com/repos/{full_name}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "eyes-and-ears/1.0",
    }
    if GITHUB_API_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_API_TOKEN}"

    r = requests.get(url, headers=headers, timeout=10)

    if r.status_code == 200:
        data = r.json()
        is_public = (data.get("private") is False)
        return True, is_public
    elif r.status_code == 404:
        # Either still private or not created yet.
        return False, False
    else:
        # Rate limited / server hiccup / etc.
        print(f"[{full_name}] Non-OK GitHub status {r.status_code}", file=sys.stderr)
        return False, False

def send_slack_alert(full_name):
    text = (
        f":rotating_light: {full_name} is PUBLIC.\n"
        f"https://github.com/{full_name}"
    )
    resp = requests.post(
        SLACK_WEBHOOK_URL,
        json={"text": text},
        timeout=10,
    )
    resp.raise_for_status()

def ensure_repo_state(state, repo):
    # ensure each watched repo has a tracking record
    if repo not in state:
        state[repo] = {"alert_sent": False}

def git_has_changes():
    # returns True if state.json has uncommitted changes
    result = subprocess.run(
        ["git", "status", "--porcelain", "state.json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip() != ""

def git_commit_and_push():
    # Configure bot identity (local to this job only)
    subprocess.run(["git", "config", "user.name", "eyes-and-ears-bot"], check=True)
    subprocess.run(
        ["git", "config", "user.email", "eyes-and-ears-bot@example.com"],
        check=True,
    )

    # Commit updated state.json
    subprocess.run(["git", "add", "state.json"], check=True)
    subprocess.run(
        ["git", "commit", "-m", "Update repo visibility state [bot]"],
        check=True,
    )

    # Push to main using a tokenized remote URL
    repo_url = os.environ["GIT_REMOTE_URL"]
    subprocess.run(["git", "push", repo_url, "HEAD:main"], check=True)

def main():
    repos_to_watch = load_config()
    state = load_state()

    # Keep a deep copy in case we want to diff later (not strictly required)
    state_before = copy.deepcopy(state)

    for repo in repos_to_watch:
        ensure_repo_state(state, repo)

        exists, is_public = get_repo_status(repo)
        already_alerted = state[repo]["alert_sent"]

        if exists and is_public and not already_alerted:
            # First time we confirm it's public -> alert once
            send_slack_alert(repo)
            state[repo]["alert_sent"] = True

    # Write state file (may or may not have changed)
    save_state(state)

    # If state.json changed compared to HEAD, push commit
    if git_has_changes():
        git_commit_and_push()

if __name__ == "__main__":
    main()
```

Key behaviors:

* Iterates all repos in `config.json`.
* For each repo:

  * Ensures there's an entry in `state.json`.
  * Checks if it just became public.
  * Sends Slack alert once.
  * Marks `alert_sent` = true.
* At the end, commits `state.json` back to `main` if it changed.

---

## 3. GitHub Actions workflow

Create `.github/workflows/watch-public.yml` with:

```yaml
name: Watch repo visibility

on:
  schedule:
    - cron: "*/5 * * * *"   # run every 5 minutes
  workflow_dispatch: {}      # allow manual trigger

jobs:
  watch:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          # use a PAT so we can push changes back
          token: ${{ secrets.GH_PAT }}

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install requests

      - name: Run watcher
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
          # Reuse GH_PAT for both GitHub API auth (rate limit)
          # and for authenticated push.
          GITHUB_API_TOKEN: ${{ secrets.GH_PAT }}
          GIT_REMOTE_URL: https://${{ secrets.GH_PAT }}@github.com/${{ github.repository }}.git
        run: |
          python watcher.py
```

Notes:

* The workflow runs every 5 minutes.
* We also allow manual dispatch for testing.
* We pass in secrets as env vars.

---

## 4. Secrets setup

In the `eyes-and-ears` repo, go to:
**Settings → Secrets and variables → Actions → New repository secret**

Create:

1. `SLACK_WEBHOOK_URL`

   * Value: Incoming Webhook URL from your Slack app / channel.
   * This is where alerts post.

2. `GH_PAT`

   * Value: Personal Access Token (classic) from your GitHub account.
   * Required scopes:

     * `repo` (so Actions can push commits to `eyes-and-ears`).
   * We also use this token for GitHub API calls to avoid hitting the low unauthenticated rate limit.

No other secrets are required.

---

## 5. Usage / lifecycle

### 5.1 Adding repos to watch

To add a new repo:

1. Edit `config.json` and append `"owner/repo"` to `"repos"`.
2. Commit to `main`.

Next scheduled run will:

* Notice the new repo, add it to `state.json` (with `"alert_sent": false`),
* Start polling it.

### 5.2 Alert behavior

* As soon as a watched repo becomes publicly visible (`200` + `"private": false`):

  * Slack gets a one-time `:rotating_light:` alert with the repo URL.
  * `state.json` flips that repo’s `"alert_sent"` to `true`.
  * That updated `state.json` is committed back to `main` automatically.
* Future runs will see `"alert_sent": true` and will not alert again for that repo.

### 5.3 Removing repos

* To stop watching a repo, just remove it from `config.json` and commit.
* We will keep its state in `state.json` (harmless).
  You can also manually clean `state.json` if you want, but it’s optional.

---

## 6. Operational constraints / assumptions

1. Default branch is called `main`.

   * If the repo default branch is `master` or something else, update:

     * The push target in `git push` inside `watcher.py`.
     * The branch checkout defaults in the workflow if needed.

2. Branch protection rules:

   * If `main` is protected and disallows direct pushes from PATs / bots, the final `git push` will fail.
   * If that’s the case, either:

     * Grant that PAT user permission to push to `main`, OR
     * Change `git_commit_and_push()` to push to a dedicated branch (e.g. `state-updates`) and accept that `state.json` in `main` may lag behind.
       (If `state.json` in `main` lags, you risk duplicate Slack alerts after a runner without that branch state. Easiest fix is: don’t protect `main` against this bot.)

3. Poll frequency (`*/5 * * * *`):

   * Every 5 minutes is a good trade-off (rate limit safe and near-real-time detection).
   * You can go to 1 minute if you want, but watch rate limits.

4. Rate limiting:

   * Unauthenticated GitHub API is ~60 req/hr/IP.
   * With `GH_PAT`, limit is much higher (~5k/hr).
   * We pass `GH_PAT` into `watcher.py` as `GITHUB_API_TOKEN` for this reason.

---

## 7. Deliverables checklist for the agent

**Create repo structure:**

* [ ] Create repo `eyes-and-ears`.
* [ ] Add files: `PLAN.md`, `watcher.py`, `config.json`, `state.json`, `.github/workflows/watch-public.yml`.

**Write initial file contents:**

* [ ] Put content from sections 2.1, 2.2, 2.3, and 3 into the respective files verbatim.

**Security setup:**

* [ ] In GitHub repo settings → Actions secrets:

  * [ ] Add `SLACK_WEBHOOK_URL`.
  * [ ] Add `GH_PAT`.

**Repo config:**

* [ ] Ensure default branch is `main`.
* [ ] Ensure branch protection (if any) still allows the PAT user to push to `main`.

**Dry run test:**

* [ ] Temporarily modify `watcher.py` locally before commit (not pushed) to force `exists=True`, `is_public=True` for one repo to confirm Slack fires.
* [ ] Revert that change, commit real version.
* [ ] Manually run the workflow (`workflow_dispatch`) in GitHub Actions.
* [ ] Observe:

  * [ ] No Python errors.
  * [ ] `state.json` gets committed back if it changed.
  * [ ] No Slack spam unless we forced it.

After that, the system is live.

---

## 8. Expected steady state

* GitHub Actions runs every 5 minutes.
* If nothing is public yet: no Slack messages, no commits.
* The moment any watched repo becomes public:

  * One Slack alert.
  * A single commit changing `state.json`.
  * After that, silence.

This completes the design for `eyes-and-ears`.

```
::contentReference[oaicite:0]{index=0}
```
