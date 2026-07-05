#!/usr/bin/env python3
import os
import re
import sys
import subprocess

# Regex patterns for common secrets
SECRET_PATTERNS = {
    "Google/Gemini API Key": re.compile(r"AIzaSy[a-zA-Z0-9_-]{35}"),
    "Generic Private Key": re.compile(r"-----BEGIN (?:[A-Z0-9\s]+ )?PRIVATE KEY-----"),
    "Twitch Client Secret Pattern": re.compile(r"TWITCH_CLIENT_SECRET\s*=\s*['\"][a-zA-Z0-9]{30}['\"]"),
    "Generic API Key Assignment": re.compile(r"(?:api_key|client_secret|client_id|password|token|secret)\s*=\s*['\"][a-zA-Z0-9_-]{20,}['\"]", re.IGNORECASE),
}

# Substrings that represent fake/mock secrets in tests or docs and should be allowed
WHITELIST_SUBSTRINGS = [
    "AIzaSyTest",
    "AIzaSyFakeKeyForTest",
    "AIzaSyTestKey123",
    "AIzaSyTestApiKey",
    "fake_yt_key",
    "new_fake_key",
    "different_key",
    "primary_key_456",
    "test_token",
    "your-api-key-here",
    "gemini_session_key",
    "visitor_id",
]

def get_tracked_files():
    """Gets all files tracked by Git in the current repository."""
    try:
        output = subprocess.check_output(["git", "ls-files"], text=True)
        return [line.strip() for line in output.splitlines() if line.strip()]
    except Exception as e:
        print(f"Error listing git files: {e}", file=sys.stderr)
        return []

def scan_file(filepath):
    """Scans a file for potential secrets, returning a list of findings."""
    findings = []
    if not os.path.isfile(filepath):
        return findings

    # Skip binary files or lock files
    if filepath.endswith((".png", ".jpg", ".jpeg", ".ico", ".pdf", ".lock", ".pyc", ".db")):
        return findings

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line_num, line in enumerate(f, 1):
                for label, pattern in SECRET_PATTERNS.items():
                    matches = pattern.findall(line)
                    for match in matches:
                        # Check if match contains whitelisted substrings
                        if any(wl in match or wl in line for wl in WHITELIST_SUBSTRINGS):
                            continue
                        
                        # Extra validation: if it's a generic assignment, make sure it's not a placeholder
                        if label == "Generic API Key Assignment":
                            # e.g., if it has "placeholder" or "your-" in it, skip
                            lower_match = match.lower()
                            if "placeholder" in lower_match or "your-" in lower_match or "fake" in lower_match:
                                continue

                        findings.append({
                            "line_num": line_num,
                            "label": label,
                            "match": match,
                            "line_content": line.strip()
                        })
    except Exception as e:
        print(f"Could not read {filepath}: {e}", file=sys.stderr)
    
    return findings

def main():
    print("Starting security secret scanner...")
    
    # 1. Get files to scan
    if len(sys.argv) > 1:
        # Scan specified directories/files
        files_to_scan = []
        for path in sys.argv[1:]:
            if os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for file in files:
                        files_to_scan.append(os.path.join(root, file))
            else:
                files_to_scan.append(path)
    else:
        # Default: scan tracked files only
        print("Scanning tracked Git files...")
        files_to_scan = get_tracked_files()

    # Exclude the scan script itself
    script_name = os.path.basename(__file__)
    files_to_scan = [f for f in files_to_scan if os.path.basename(f) != script_name]

    total_findings = 0
    failed = False

    for filepath in files_to_scan:
        # Skip scanning itself just in case
        if filepath.endswith("scan_secrets.py"):
            continue
            
        findings = scan_file(filepath)
        if findings:
            print(f"\n[!] Potentially exposed secret(s) found in {filepath}:")
            for f in findings:
                # Redact match for display
                match_str = f["match"]
                redacted = match_str[:4] + "..." + match_str[-4:] if len(match_str) > 8 else "..."
                print(f"  Line {f['line_num']} [{f['label']}]: {redacted}")
                print(f"    Content: {f['line_content'][:100]}")
                total_findings += 1
            
            # If the file is a tracked git file, it is a hard failure
            # If it's a git-ignored file (like .env), we print warning but don't fail the build
            # unless the user specified a directory directly
            is_tracked = filepath in get_tracked_files()
            if is_tracked:
                failed = True

    print("\n--- Scan Summary ---")
    print(f"Scanned {len(files_to_scan)} files.")
    print(f"Found {total_findings} potential secret exposures.")

    if failed:
        print("\n[FAIL] Exposed secrets found in tracked files! Please remove them before committing.")
        sys.exit(1)
    else:
        print("\n[SUCCESS] No exposed secrets found in tracked files.")
        sys.exit(0)

if __name__ == "__main__":
    main()
