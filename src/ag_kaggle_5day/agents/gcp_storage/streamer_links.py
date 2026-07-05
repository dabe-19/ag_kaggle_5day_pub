from __future__ import annotations

import datetime
import logging
from typing import Optional

from google.cloud import bigquery

logger = logging.getLogger("streamer_advisor.gcp_storage")
_streamer_links_memo: dict[str, Optional[dict]] = {}


def get_streamer_autocomplete(q: str) -> list[dict]:
    """Retrieves unique streamer handles matching the prefix q from cached games
    and Firestore, resolving friendly display names and platforms.
    """
    from ag_kaggle_5day.agents.advisor import get_cached_games
    from ag_kaggle_5day.agents.gcp_storage import (
        get_firestore_client,
        resolve_streamer_link,
    )

    try:
        games = get_cached_games()
    except Exception:
        games = []

    q = q.lower().strip()
    matches = {}  # handle_lower -> dict

    # 1. Check cached games list
    for g in games:
        for s in g.get("top_streamers", []):
            name = s.get("user_name", "")
            login = s.get("user_login", "")
            platform = s.get("platform", "twitch")
            if q in name.lower() or q in login.lower():
                matches[login.lower()] = {
                    "handle": login,
                    "display_name": name or login,
                    "platform": platform,
                }

    # 2. Check Firestore profiles
    client = get_firestore_client()
    if client:
        try:
            docs = client.collection("streamer_profiles").stream()
            for doc in docs:
                doc_id = doc.id
                data = doc.to_dict()
                disp_name = (
                    data.get("youtube_title")
                    or data.get("twitch_display_name")
                    or data.get("display_name")
                    or doc_id
                )
                is_yt = doc_id.lower().startswith("uc")
                platform = data.get("platform", "youtube" if is_yt else "twitch")

                if q in doc_id.lower() or q in disp_name.lower():
                    matches[doc_id.lower()] = {
                        "handle": doc_id,
                        "display_name": disp_name,
                        "platform": platform,
                    }
        except Exception as fs_err:
            logger.warning(f"Failed to query Firestore for autocomplete: {fs_err}")

    # Resolve display names for YouTube channels
    for h_lower, item in list(matches.items()):
        if h_lower.startswith("uc") and item["display_name"] == item["handle"]:
            try:
                link_info = resolve_streamer_link(item["handle"], client)
                if link_info and link_info.get("display_name"):
                    item["display_name"] = link_info["display_name"]
            except Exception:
                pass

    sorted_list = sorted(matches.values(), key=lambda x: x["display_name"].lower())
    return sorted_list[:10]


def prepopulate_streamer_links_cache(fs_client=None) -> None:
    """Pre-populates the streamer links in-memory cache from Firestore."""
    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    if not fs_client:
        fs_client = get_firestore_client()
    if not fs_client:
        return
    try:
        docs = fs_client.collection("streamer_account_links").stream()
        count = 0
        for doc in docs:
            data = doc.to_dict()
            tw = data.get("twitch_handle")
            yt = data.get("youtube_channel_id")
            if tw:
                _streamer_links_memo[tw.strip().lower()] = data
            if yt:
                _streamer_links_memo[yt.strip().lower()] = data
            count += 1
        logger.info(
            f"Pre-populated streamer links cache with {count} account mappings."
        )
    except Exception as e:
        logger.warning(f"Failed to pre-populate streamer links cache: {e}")


def store_streamer_account_link(
    twitch_handle: str,
    youtube_channel_id: str,
    display_name: str,
    manually_verified: bool = False,
    fs_client=None,
) -> None:
    """Stores a link between a Twitch handle and YouTube channel ID in Firestore

    and BigQuery."""
    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    tw = twitch_handle.strip().lower()
    yt_doc_id = youtube_channel_id.strip().lower()
    yt_field_val = youtube_channel_id.strip()
    disp = display_name.strip()

    # 1. Store in Firestore
    if not fs_client:
        fs_client = get_firestore_client()
    if fs_client:
        try:
            link_data = {
                "twitch_handle": tw,
                "youtube_channel_id": yt_field_val,
                "display_name": disp,
                "manually_verified": manually_verified,
            }
            # Use lowercased youtube_channel_id as document ID
            fs_client.collection("streamer_account_links").document(yt_doc_id).set(
                link_data
            )

            # Update cache memo
            _streamer_links_memo[tw] = link_data
            _streamer_links_memo[yt_doc_id] = link_data
            logger.info(
                f"Stored streamer link in Firestore: {tw} <-> {yt_field_val} ({disp})"
            )
        except Exception as e:
            logger.error(f"Failed to store streamer link in Firestore: {e}")

    # 2. Log to BigQuery
    from ag_kaggle_5day.agents.gcp_storage import get_bigquery_client

    bq = get_bigquery_client()
    if bq:
        try:
            project = bq.project
            dataset_id = f"{project}.streamer_metrics"
            table_id = f"{dataset_id}.account_links"

            # Ensure dataset exists
            try:
                bq.get_dataset(dataset_id)
            except Exception:
                dataset = bigquery.Dataset(dataset_id)
                dataset.location = "US"
                bq.create_dataset(dataset, timeout=30)

            # Ensure table exists
            schema = [
                bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
                bigquery.SchemaField("twitch_handle", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("youtube_channel_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("display_name", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("manually_verified", "BOOLEAN", mode="REQUIRED"),
            ]
            try:
                bq.get_table(table_id)
            except Exception:
                table = bigquery.Table(table_id, schema=schema)
                bq.create_table(table, timeout=30)
                logger.info(f"Created BigQuery account links table: {table_id}")

            now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
            row = {
                "timestamp": now_str,
                "twitch_handle": tw,
                "youtube_channel_id": yt_field_val,
                "display_name": disp,
                "manually_verified": manually_verified,
            }
            errors = bq.insert_rows_json(table_id, [row], timeout=30)
            if errors:
                logger.error(f"Failed to insert account link into BigQuery: {errors}")
            else:
                logger.info(f"Logged account link in BigQuery: {tw} <-> {yt_field_val}")
        except Exception as e:
            logger.error(f"Failed to log account link in BigQuery: {e}")


def resolve_streamer_link(handle: str, fs_client=None) -> Optional[dict]:
    if not handle:
        return None
    h = handle.strip().lower()
    if h in _streamer_links_memo:
        return _streamer_links_memo[h]

    res = _resolve_streamer_link_nocache(h, fs_client)
    _streamer_links_memo[h] = res
    if res:
        tw = res.get("twitch_handle")
        yt = res.get("youtube_channel_id")
        if tw:
            _streamer_links_memo[tw.strip().lower()] = res
        if yt:
            _streamer_links_memo[yt.strip().lower()] = res
    return res


def get_case_preserved_youtube_id(
    lowercase_id: str, twitch_handle: Optional[str], fs_client
) -> str:
    if not lowercase_id:
        return lowercase_id

    # Fast-path: return immediately if already case-preserved
    if len(lowercase_id) == 24 and any(c.isupper() for c in lowercase_id[2:]):
        return lowercase_id

    # 0. Check streamer_account_links direct map first
    try:
        link_doc = (
            fs_client.collection("streamer_account_links").document(lowercase_id).get()
        )
        if link_doc.exists:
            link_data = link_doc.to_dict() or {}
            val = link_data.get("youtube_channel_id")
            if val and len(val) == 24 and any(c.isupper() for c in val[2:]):
                return val
    except Exception as e:
        logger.warning(
            f"Failed to lookup case-preserved ID in streamer_account_links: {e}"
        )

    # 1. Try Firestore caches first
    doc_ref = fs_client.collection("streamer_sentiment").document(lowercase_id).get()
    if doc_ref.exists:
        data = doc_ref.to_dict() or {}
        val = data.get("youtube_channel_id") or data.get("streamer_handle")
        if val and len(val) == 24 and any(c.isupper() for c in val[2:]):
            return val

    doc_ref = fs_client.collection("streamer_profiles").document(lowercase_id).get()
    if doc_ref.exists:
        data = doc_ref.to_dict() or {}
        val = data.get("youtube_channel_id") or data.get("streamer_handle")
        if val and len(val) == 24 and any(c.isupper() for c in val[2:]):
            return val

    # 2. If lowercase and twitch_handle exists, scrape YouTube to resolve
    # case-preserved ID
    if twitch_handle:
        try:
            import re

            import requests

            url = f"https://www.youtube.com/@{twitch_handle}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",  # noqa: E501
                "Accept-Language": "en-US,en;q=0.9",
            }
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                match = re.search(r"UC[a-zA-Z0-9_-]{22}", resp.text)
                if match:
                    val = match.group(0)
                    if val.lower() == lowercase_id.lower():
                        logger.info(
                            f"Self-healing: Resolved case-preserved YouTube ID '{val}' for twitch '{twitch_handle}'"  # noqa: E501
                        )
                        # Update Firestore link document to heal it permanently!
                        doc_id = twitch_handle.strip().lower()
                        fs_client.collection("streamer_account_links").document(
                            doc_id
                        ).update({"youtube_channel_id": val})
                        # Also update the reverse lookup link document if it exists
                        rev_doc = fs_client.collection(
                            "streamer_account_links"
                        ).document(lowercase_id)
                        if rev_doc.get().exists:
                            rev_doc.update({"youtube_channel_id": val})
                        return val
        except Exception as e:
            logger.warning(
                f"Self-healing YouTube ID lookup failed for twitch @{twitch_handle}: {e}"  # noqa: E501
            )
    else:
        # 3. If no twitch_handle, try using display_name/title from the profile doc to
        # resolve via custom handle
        try:
            doc_ref = (
                fs_client.collection("streamer_profiles").document(lowercase_id).get()
            )
            if doc_ref.exists:
                data = doc_ref.to_dict() or {}
                disp = data.get("display_name") or data.get("youtube_title")
                if disp:
                    import os
                    import re

                    import requests

                    # 3a. Try official YouTube Search API (highly reliable and won't
                    # get blocked by Captcha)
                    api_key = os.environ.get("YOUTUBE_API_KEY")
                    if api_key:
                        try:
                            search_url = "https://www.googleapis.com/youtube/v3/search"
                            params = {
                                "part": "snippet",
                                "type": "channel",
                                "q": disp,
                                "maxResults": 10,
                                "key": api_key,
                            }
                            resp = requests.get(search_url, params=params, timeout=5)
                            if resp.status_code == 200:
                                items = resp.json().get("items", [])
                                for item in items:
                                    channel_id = item.get("id", {}).get("channelId")
                                    if (
                                        channel_id
                                        and channel_id.lower() == lowercase_id.lower()
                                    ):
                                        logger.info(
                                            f"Self-healing: Resolved case-preserved YouTube ID '{channel_id}' via API search for '{disp}'"  # noqa: E501
                                        )
                                        # Update Firestore profile document to heal it
                                        fs_client.collection(
                                            "streamer_profiles"
                                        ).document(lowercase_id).update(
                                            {
                                                "youtube_channel_id": channel_id,
                                                "streamer_handle": channel_id,
                                            }
                                        )
                                        return channel_id
                        except Exception as api_err:
                            logger.warning(
                                f"Self-healing YouTube ID lookup via API failed for standalone {lowercase_id}: {api_err}"  # noqa: E501
                            )

                    # 3b. Fallback to web scraping if API search failed or key not
                    # available
                    # Remove spaces and special characters for handle format
                    clean_name = re.sub(r"[^a-zA-Z0-9]", "", disp)
                    url = f"https://www.youtube.com/@{clean_name}"
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",  # noqa: E501
                        "Accept-Language": "en-US,en;q=0.9",
                    }
                    resp = requests.get(url, headers=headers, timeout=5)
                    if resp.status_code == 200:
                        match = re.search(r"UC[a-zA-Z0-9_-]{22}", resp.text)
                        if match:
                            val = match.group(0)
                            if val.lower() == lowercase_id.lower():
                                logger.info(
                                    f"Self-healing: Resolved case-preserved YouTube ID '{val}' for standalone channel '{disp}'"  # noqa: E501
                                )
                                # Update Firestore profile document to heal it
                                fs_client.collection("streamer_profiles").document(
                                    lowercase_id
                                ).update(
                                    {"youtube_channel_id": val, "streamer_handle": val}
                                )
                                return val
        except Exception as e:
            logger.warning(
                f"Self-healing YouTube ID lookup failed for standalone {lowercase_id}: {e}"  # noqa: E501
            )

    return lowercase_id


def _resolve_streamer_link_nocache(handle: str, fs_client=None) -> Optional[dict]:
    """
    Given a handle (Twitch handle or YouTube channel ID), resolves it to a dict:
    {"twitch_handle": "...", "youtube_channel_id": "...", "display_name": "..."}
    or None if no linkage is found.
    Checks Firestore 'streamer_account_links' first. If missing, runs heuristic search
    over cached games list in Firestore and creates/caches the link.
    """
    from ag_kaggle_5day.agents.gcp_storage import (
        get_firestore_client,
    )

    if not fs_client:
        fs_client = get_firestore_client()
    if not fs_client:
        return None

    h = handle.strip().lower()
    if not h or "/" in h:
        return None
    is_yt_format = h.startswith("uc")

    try:
        # 1. Check direct map in Firestore
        if is_yt_format:
            doc = fs_client.collection("streamer_account_links").document(h).get()
            if doc.exists:
                res = doc.to_dict()
                if res and res.get("youtube_channel_id"):
                    res["youtube_channel_id"] = get_case_preserved_youtube_id(
                        res["youtube_channel_id"], res.get("twitch_handle"), fs_client
                    )
                return res

            # Query by youtube_channel_id field (case-insensitive list search)
            from google.cloud.firestore_v1.base_query import FieldFilter

            docs = (
                fs_client.collection("streamer_account_links")
                .where(
                    filter=FieldFilter(
                        "youtube_channel_id", "in", [h, h.lower(), h.upper()]
                    )
                )
                .limit(1)
                .stream()
            )
            for doc in docs:
                res = doc.to_dict()
                if res and res.get("youtube_channel_id"):
                    res["youtube_channel_id"] = get_case_preserved_youtube_id(
                        res["youtube_channel_id"], res.get("twitch_handle"), fs_client
                    )
                return res
        else:
            # Query by twitch_handle
            from google.cloud.firestore_v1.base_query import FieldFilter

            docs = (
                fs_client.collection("streamer_account_links")
                .where(filter=FieldFilter("twitch_handle", "==", h))
                .limit(1)
                .stream()
            )
            for doc in docs:
                res = doc.to_dict()
                if res and res.get("youtube_channel_id"):
                    res["youtube_channel_id"] = get_case_preserved_youtube_id(
                        res["youtube_channel_id"], res.get("twitch_handle"), fs_client
                    )
                return res
    except Exception as e:
        logger.warning(f"Error checking streamer_account_links for '{h}': {e}")

    # 2. Run heuristics fallback (offline sentiment cache matching)
    try:
        from google.cloud.firestore_v1.base_query import FieldFilter

        if is_yt_format:
            # 1. Fetch channel title from YouTube sentiment cache or profiles cache
            yt_doc = fs_client.collection("streamer_sentiment").document(h).get()
            if not yt_doc.exists:
                yt_doc = fs_client.collection("streamer_profiles").document(h).get()

            channel_title = None
            case_preserved_yt_id = None
            if yt_doc.exists:
                yt_data = yt_doc.to_dict()
                channel_title = yt_data.get("user_name") or yt_data.get("youtube_title")
                case_preserved_yt_id = yt_data.get("youtube_channel_id") or yt_data.get(
                    "streamer_handle"
                )

            # 2. If not found in cache, fall back to cached games list
            if not channel_title:
                try:
                    from ag_kaggle_5day.agents.advisor import get_cached_games

                    cached_games = get_cached_games() or []
                    for g in cached_games:
                        top_s = g.get("top_streamers") or []
                        for s in top_s:
                            if (
                                s.get("platform") == "youtube"
                                and s.get("user_login", "").strip().lower() == h
                            ):
                                channel_title = s.get("user_name")
                                case_preserved_yt_id = s.get("user_login")
                                break
                        if channel_title:
                            break
                except Exception:
                    pass

            if channel_title:
                twitch_cand = channel_title.strip().lower().replace(" ", "")
                # Verify if the Twitch candidate exists in profiles or sentiment caches
                is_valid = (
                    twitch_cand
                    and "/" not in twitch_cand
                    and all(c.isalnum() or c == "_" for c in twitch_cand)
                )
                if is_valid:
                    prof_doc = (
                        fs_client.collection("streamer_profiles")
                        .document(twitch_cand)
                        .get()
                    )
                    sent_doc = (
                        fs_client.collection("streamer_sentiment")
                        .document(twitch_cand)
                        .get()
                    )
                    prof_exists = prof_doc.exists
                    sent_exists = sent_doc.exists
                else:
                    prof_exists = False
                    sent_exists = False

                if prof_exists or sent_exists:
                    store_streamer_account_link(
                        twitch_handle=twitch_cand,
                        youtube_channel_id=case_preserved_yt_id or h,
                        display_name=channel_title,
                        manually_verified=False,
                        fs_client=fs_client,
                    )
                    return {
                        "twitch_handle": twitch_cand,
                        "youtube_channel_id": case_preserved_yt_id or h,
                        "display_name": channel_title,
                        "manually_verified": False,
                    }
                else:
                    return {
                        "twitch_handle": None,
                        "youtube_channel_id": case_preserved_yt_id or h,
                        "display_name": channel_title,
                        "manually_verified": False,
                    }
        else:
            # 1. Scan YouTube sentiment cache documents for matching name
            matched_yt_id = None
            matched_yt_name = None
            try:
                docs = (
                    fs_client.collection("streamer_sentiment")
                    .where(filter=FieldFilter("platform", "==", "youtube"))
                    .stream()
                )
                for doc in docs:
                    data = doc.to_dict()
                    yt_name = data.get("user_name", "").strip().lower().replace(" ", "")
                    if yt_name == h:
                        matched_yt_id = doc.id
                        matched_yt_name = data.get("user_name")
                        break
            except Exception:
                pass

            # 2. Fall back to cached games if cache scan failed
            if not matched_yt_id:
                try:
                    from ag_kaggle_5day.agents.gcp_storage import get_cached_games

                    cached_games = get_cached_games() or []
                    for g in cached_games:
                        top_s = g.get("top_streamers") or []
                        for s in top_s:
                            if s.get("platform") == "youtube":
                                yt_name = (
                                    s.get("user_name", "")
                                    .strip()
                                    .lower()
                                    .replace(" ", "")
                                )
                                if yt_name == h:
                                    matched_yt_id = (
                                        s.get("user_login", "").strip().lower()
                                    )
                                    matched_yt_name = s.get("user_name")
                                    break
                        if matched_yt_id:
                            break
                except Exception:
                    pass

            if matched_yt_id:
                store_streamer_account_link(
                    twitch_handle=h,
                    youtube_channel_id=matched_yt_id,
                    display_name=matched_yt_name,
                    manually_verified=False,
                    fs_client=fs_client,
                )
                return {
                    "twitch_handle": h,
                    "youtube_channel_id": matched_yt_id,
                    "display_name": matched_yt_name,
                    "manually_verified": False,
                }
    except Exception as heuristic_err:
        logger.warning(
            f"Failed to run account links heuristics for '{h}': {heuristic_err}"
        )

    return None


def get_new_moments_counts_from_bq() -> dict[str, int]:
    """Queries BigQuery to count the number of new moments for each streamer
    since their last fabric update (using last_updated in streamer_profile_fabric).
    """
    from ag_kaggle_5day.agents.gcp_storage import get_bigquery_client

    bq = get_bigquery_client()
    counts = {}
    if not bq:
        return counts
    try:
        project = bq.project
        query = f"""
            SELECT
              LOWER(m.streamer_handle) as streamer_handle,
              COUNT(m.timestamp) as new_moments_count
            FROM
              `{project}.streamer_metrics.streamer_sentiment_moments` m
            LEFT JOIN
              `{project}.streamer_metrics.streamer_profile_fabric` f
            ON
              LOWER(m.streamer_handle) = LOWER(f.streamer_handle)
            WHERE
              f.last_updated IS NULL OR m.timestamp > f.last_updated
            GROUP BY
              LOWER(m.streamer_handle)
        """
        query_job = bq.query(query)
        for row in query_job:
            h = row.streamer_handle
            if h:
                counts[h.strip().lower()] = int(row.new_moments_count)
    except Exception as e:
        logger.error(f"Error querying new moments counts from BigQuery: {e}")
    return counts


def get_new_moments_counts_from_fs() -> dict[str, int]:
    """Fallback using Firestore to count new moments since last fabric aggregation."""
    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    fs = get_firestore_client()
    counts = {}
    if not fs:
        return counts
    try:
        # 1. Fetch last_aggregated for all streamers from streamer_profiles
        profile_updates = {}
        docs = fs.collection("streamer_profiles").select(["last_aggregated"]).stream()
        for doc in docs:
            data = doc.to_dict()
            ts = data.get("last_aggregated")
            ts_val = 0.0
            if ts:
                if hasattr(ts, "timestamp"):
                    ts_val = ts.timestamp()
                else:
                    try:
                        ts_val = float(ts)
                    except Exception:
                        pass
            profile_updates[doc.id.strip().lower()] = ts_val

        # 2. Fetch all moments from streamer_moments
        moments_docs = (
            fs.collection("streamer_moments")
            .select(["streamer_handle", "timestamp"])
            .stream()
        )
        for doc in moments_docs:
            data = doc.to_dict()
            h = data.get("streamer_handle", "").strip().lower()
            ts = data.get("timestamp", 0.0)
            if h:
                last_update = profile_updates.get(h, 0.0)
                if ts > last_update:
                    counts[h] = counts.get(h, 0) + 1
    except Exception as e:
        logger.error(f"Error counting new moments from Firestore: {e}")
    return counts
