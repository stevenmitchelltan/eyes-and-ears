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

    # Pull latest changes before committing
    repo_url = os.environ["GIT_REMOTE_URL"]
    subprocess.run(["git", "fetch", repo_url, "main"], check=True)
    subprocess.run(["git", "rebase", f"{repo_url}/main"], check=True)

    # Commit updated state.json
    subprocess.run(["git", "add", "state.json"], check=True)
    subprocess.run(
        ["git", "commit", "-m", "Update repo visibility state [bot]"],
        check=True,
    )

    # Push to main using a tokenized remote URL
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

