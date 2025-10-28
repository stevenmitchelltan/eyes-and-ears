# eyes-and-ears

A GitHub repository monitoring system that automatically detects when watched repositories become public and sends alerts to Slack.

## Overview

This tool monitors a list of GitHub repositories, checking their visibility status every 5 minutes via GitHub Actions. When a watched repository transitions from private/unavailable to public, it sends a one-time Slack alert and automatically updates its internal state to prevent duplicate notifications.

## How It Works

1. **Polling**: Every 5 minutes, the GitHub Actions workflow runs and checks each repository in `config.json`
2. **Detection**: Uses GitHub's API to determine if a repository is now publicly accessible
3. **Alerting**: Sends a Slack notification the first time a repository becomes public
4. **State Management**: Tracks alert status in `state.json` to prevent duplicate notifications
5. **Auto-commit**: Automatically commits state changes back to the repository

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure GitHub Secrets

In your GitHub repository, go to **Settings → Secrets and variables → Actions → New repository secret** and create:

#### Required Secrets

- **`SLACK_WEBHOOK_URL`**: Your Slack incoming webhook URL
  - Get this from your Slack workspace app configuration
  - Format: `https://hooks.slack.com/services/YOUR/WEBHOOK/URL`

- **`GH_PAT`**: GitHub Personal Access Token
  - Required scopes: `repo` (so Actions can push commits)
  - Also used for GitHub API calls to avoid rate limiting
  - Go to GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)

### 3. Repository Configuration

By default, the system assumes:
- Default branch is `main`
- Branch protection allows the PAT to push directly to `main`

If your repository uses different settings, you may need to adjust:
- The push target in `watcher.py` (line 206)
- Branch protection rules to allow the bot to push

## Usage

### Adding Repositories to Watch

1. Edit `config.json`
2. Add repository entries in the format `"owner/repo"`
3. Commit to `main`

Example:
```json
{
  "repos": [
    "facebookresearch/sam3",
    "openai/whisper",
    "anthropics/anthropic-sdk"
  ]
}
```

The next scheduled run will start monitoring the new repositories.

### Removing Repositories

Simply remove the repository from `config.json` and commit. The state will remain in `state.json` (harmless, but can be manually cleaned up if desired).

### Testing

You can manually trigger the workflow:
1. Go to the **Actions** tab in your GitHub repository
2. Select "Watch repo visibility"
3. Click **Run workflow**

## Files

- `watcher.py` - Main monitoring script with GitHub API polling and Slack integration
- `config.json` - List of repositories to monitor
- `state.json` - Alert tracking state (automatically managed)
- `.github/workflows/watch-public.yml` - GitHub Actions workflow definition
- `requirements.txt` - Python dependencies

## Operational Notes

### Polling Frequency

The default cron schedule runs every 5 minutes (`*/5 * * * *`). This provides a good balance between:
- Near real-time detection
- Staying within GitHub API rate limits

You can adjust this in `.github/workflows/watch-public.yml` (line 259).

### Rate Limiting

- Without authentication: ~60 requests/hour
- With `GH_PAT`: ~5,000 requests/hour

The system automatically uses the PAT for all API calls to stay within rate limits.

### Alert Behavior

- **First time public**: Slack alert + `state.json` updated + commit
- **Subsequent runs**: No alert (already alerted)
- **After alert sent**: No further alerts for that repository

## Development

### Local Testing

To test the watcher script locally:

```bash
export SLACK_WEBHOOK_URL="your-webhook-url"
export GITHUB_API_TOKEN="your-github-token"  # optional
python watcher.py
```

Note: The git push functionality requires the `GIT_REMOTE_URL` environment variable and will only work in a git repository with write access.

## License

This project is provided as-is for monitoring GitHub repository visibility.

