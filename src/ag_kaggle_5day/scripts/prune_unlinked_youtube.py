import argparse
import os
import sys

# Add src to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from ag_kaggle_5day.agents.gcp_storage import (
    get_firestore_client,
    resolve_streamer_link,
)


def prune_unlinked_channels(dry_run: bool):
    fs = get_firestore_client()
    if not fs:
        print("Firestore client not available.")
        return

    # Prepopulate links cache to avoid heavy queries
    from ag_kaggle_5day.agents.gcp_storage import prepopulate_streamer_links_cache

    prepopulate_streamer_links_cache(fs)

    collections = ["streamer_sentiment", "streamer_profiles"]
    for col_name in collections:
        print(f"\nProcessing collection: {col_name}...")
        docs = list(fs.collection(col_name).stream())
        deleted_count = 0
        total_checked = 0

        for doc in docs:
            h = doc.id
            if h.lower().startswith("uc"):
                total_checked += 1
                link = resolve_streamer_link(h, fs)
                if not link:
                    data = doc.to_dict() or {}
                    title = (
                        data.get("display_name")
                        or data.get("youtube_title")
                        or "Unknown"
                    )
                    print(f" - Found unlinked YouTube doc: {h} (name: {title})")
                    if not dry_run:
                        fs.collection(col_name).document(h).delete()
                    deleted_count += 1

        action = "Would delete" if dry_run else "Deleted"
        print(
            f"Finished {col_name}: {action} {deleted_count} "
            f"unlinked YouTube documents (out of {total_checked} checked)."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Prune unlinked YouTube channels from Firestore."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute the deletion (default is dry-run).",
    )
    args = parser.parse_args()

    dry_run = not args.execute
    if dry_run:
        print(
            "RUNNING IN DRY-RUN MODE. No deletions will be made. "
            "Pass --execute to apply changes."
        )
    else:
        print("RUNNING IN WRITE MODE. Applying deletions to Firestore.")

    prune_unlinked_channels(dry_run)
