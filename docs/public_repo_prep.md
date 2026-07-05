# Public Repository Preparation Guide

This guide describes how to securely prepare and clone this repository into a new, clean public repository for hackathon submissions or other public sharing. 

It ensures:
1. **Zero Git history leak**: None of your local development commits, messages, or branches are transferred.
2. **Zero credentials leak**: Real API keys, secret files, local configurations (`.env`, `deploy.env`, `service.yaml`), or temporary debug log files are excluded.

---

## Step-by-Step Preparation

### Step 1: Run the Secret Scanner
Before doing anything else, verify that no secrets are accidentally tracked in your current git tree:
```bash
./scripts/scan_secrets.py
```
*If this script fails, remove the flagged credentials from your code/files and commit the fixes before continuing.*

### Step 2: Create a Clean Clone (Staging Directory)
To guarantee that **only tracked files** are carried over (automatically leaving behind `.env`, `deploy.env`, and other ignored/untracked files), use the following commands to copy files into a new temporary folder:

#### Option A: Using `rsync` (Recommended on Linux/macOS)
```bash
# Define your target path (outside of the current git repository)
PUBLIC_REPO_DIR="/home/wsl-ops/projects/streamer-alignment-public"

# Create the directory
mkdir -p "$PUBLIC_REPO_DIR"

# Copy only git-tracked files
git ls-files | rsync -av --files-from=- . "$PUBLIC_REPO_DIR"
```

#### Option B: Using `tar` (If `rsync` is not installed)
```bash
PUBLIC_REPO_DIR="/home/wsl-ops/projects/streamer-alignment-public"
mkdir -p "$PUBLIC_REPO_DIR"
git archive --format=tar HEAD | tar -x -C "$PUBLIC_REPO_DIR"
```

### Step 3: Initialize the Public Repository
Navigate to the new clean folder and initialize a fresh, history-free Git repository:
```bash
cd "$PUBLIC_REPO_DIR"

# Initialize fresh Git repository
git init

# Rename default branch to main
git branch -m main

# Stage all files
git add .

# Create the first initial commit
git commit -m "Initial commit: Streamer Alignment Dashboard"
```

### Step 4: Verify the Staging Repository is Clean
While in the public repository directory, double-check that no secrets or ignored files were copied:

1. **Scan for secrets**:
   ```bash
   python3 scripts/scan_secrets.py
   ```
2. **Check for missing ignored files**:
   Ensure `.env`, `deploy.env`, `service.yaml`, and database/cache files are NOT present:
   ```bash
   ls -la
   ```
3. **Verify Git History**:
   Ensure that the git log contains exactly one commit:
   ```bash
   git log --oneline
   ```
   *(Expected output: `a1b2c3d Initial commit: Streamer Alignment Dashboard`)*

### Step 5: Push to the Public Remote
Now you can safely add your public remote and push your code:
```bash
# Add your public GitHub/GitLab repository URL
git remote add origin https://github.com/your-username/your-public-repo.git

# Push main branch
git push -u origin main
```

---

## Verification & Post-Clone Setup

### How Users Run Your Public App
Since `.env` is not carried over, clone recipients should follow these instructions (which are also documented in the `README.md`):

1. **Copy the example configuration**:
   ```bash
   cp .env.example .env
   ```
2. **Run using Poetry**:
   ```bash
   poetry install
   ```
3. **Start the application**:
   ```bash
   poetry run start
   ```
   *(If no keys are entered in `.env`, the user will be prompted to supply their own Gemini API key dynamically via the Settings drawer in the Web UI, which is fully supported.)*
