# Sync Guide: MacBook, Windows, GitHub, Streamlit

## Overview

```
┌─────────────────┐         ┌─────────────────┐
│   MacBook       │         │   Windows PC    │
│   (work/5G)     │         │   (home)        │
└────────┬────────┘         └────────┬────────┘
         │                           │
         │      git push/pull        │
         ▼                           ▼
    ┌─────────────────────────────────────┐
    │              GitHub                  │
    │  (central repository - always sync) │
    └──────────────────┬──────────────────┘
                       │
                       │ (optional)
                       ▼
              ┌─────────────────┐
              │ Streamlit Cloud │
              │ (access anywhere)│
              └─────────────────┘
```

## Initial Setup

### MacBook (First Time)

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/apex-s44-monitor.git
cd apex-s44-monitor

# Run setup script
chmod +x setup_mac.sh
./setup_mac.sh

# Fill in API keys
nano .env
```

### Windows (First Time)

```cmd
# Clone the repository
git clone https://github.com/YOUR_USERNAME/apex-s44-monitor.git
cd apex-s44-monitor

# Run setup script
setup_windows.bat

# Fill in API keys
notepad .env
```

## Daily Sync Workflow

### Starting Work (Pull Latest)

```bash
# ALWAYS pull before starting work
git pull origin main
```

### After Making Changes (Push)

```bash
# Stage all changes
git add .

# Commit with descriptive message
git commit -m "Add new feature / Fix bug / Update config"

# Push to GitHub
git push origin main
```

### Switching Devices

**Before leaving MacBook:**
```bash
git add .
git commit -m "WIP: leaving for home"
git push origin main
```

**When starting on Windows:**
```bash
git pull origin main
# Continue working...
```

## Handling Conflicts

If you see "merge conflict":

```bash
# See what's conflicting
git status

# Open conflicting file(s) and look for:
# <<<<<<< HEAD
# Your local changes
# =======
# Remote changes
# >>>>>>> main

# Edit to keep what you want, remove the markers

# Then:
git add .
git commit -m "Resolve merge conflict"
git push origin main
```

## Files to Keep in Sync

| File/Folder | Sync? | Notes |
|-------------|-------|-------|
| `monitors/*.py` | Yes | All your code |
| `snapshots/*.json` | Yes | Company data |
| `sessions/*.json` | Yes | Saved session data (positions, transcripts) - syncs across devices |
| `requirements.txt` | Yes | Dependencies |
| `.env` | **NO** | API keys - different per machine |
| `venv/` | **NO** | Virtual environment - rebuild |
| `__pycache__/` | **NO** | Auto-generated |

### Session Persistence

Your trading positions and transcript data are now saved to `sessions/` as JSON files.
This means:
- **Positions survive browser refresh** - no more losing your position tracker
- **Data syncs between Mac and Windows** - commit and push on one device, pull on the other
- **No need to shut down first** - just push your changes before switching devices

## .gitignore (Already Configured)

Make sure these are NOT synced:

```gitignore
# Virtual environment
venv/
.venv/

# API keys (NEVER commit these!)
.env
*.env

# Python cache
__pycache__/
*.pyc

# IDE
.vscode/
.idea/

# OS files
.DS_Store
Thumbs.db
```

## Streamlit Cloud (Optional)

Access your monitor from anywhere without local setup.

### Setup

1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Connect your GitHub account
3. Select `apex-s44-monitor` repository
4. Main file: `apex_monitor.py`
5. Add secrets (Settings > Secrets):

```toml
OPENAI_API_KEY = "sk-..."
DEEPGRAM_API_KEY = "..."
TWITTER_BEARER_TOKEN = "..."
```

### Access

Your app will be at:
`https://YOUR_APP_NAME.streamlit.app`

**Note:** Live transcription (audio capture) won't work on Streamlit Cloud -
that requires local machine access. Use Cloud for:
- Sentiment analysis (paste transcripts)
- SEC filing monitor
- LME risk dashboard
- Position tracker

## Quick Reference

### Mac Commands
```bash
# Start app
source venv/bin/activate && streamlit run apex_monitor.py

# Sync
git pull && git add . && git commit -m "msg" && git push

# Update dependencies
pip install -r requirements.txt
```

### Windows Commands
```cmd
# Start app
venv\Scripts\activate && streamlit run apex_monitor.py

# Sync
git pull && git add . && git commit -m "msg" && git push

# Update dependencies
pip install -r requirements.txt
```

## Troubleshooting

### "Permission denied" on Mac
```bash
chmod +x setup_mac.sh
```

### "Module not found"
```bash
# Make sure venv is activated
source venv/bin/activate  # Mac
venv\Scripts\activate     # Windows

# Reinstall
pip install -r requirements.txt
```

### "Merge conflict"
```bash
# See conflicts
git status

# Reset if needed (CAREFUL - loses local changes!)
git stash
git pull origin main
git stash pop
```

### Different Python versions
Both machines should use Python 3.10+. Check with:
```bash
python --version
```
