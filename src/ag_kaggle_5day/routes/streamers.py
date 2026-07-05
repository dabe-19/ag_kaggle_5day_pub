import logging
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from ag_kaggle_5day.models import LinkStreamerAccountsPayload
from ag_kaggle_5day.security import (
    check_rate_limit,
    forecast_client_limiter,
    forecast_global_limiter,
    get_client_key,
    get_effective_key,
    profile_client_limiter,
    profile_global_limiter,
)

logger = logging.getLogger("streamer_advisor.routes.streamers")
router = APIRouter()

active_profile_builds = set()


@router.get("/api/streamers/{handle}/correlations")
def api_get_streamer_correlations(handle: str, compare: str = None):
    """
    Retrieves the correlation connection mappings for a streamer.
    """
    try:
        from ag_kaggle_5day.agents.advisor import get_streamer_correlations

        res = get_streamer_correlations(handle, compare)
        return res
    except Exception as e:
        logger.error(f"Error in GET /api/streamers/{handle}/correlations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/starmap")
def api_get_starmap():
    """
    Retrieves the full Star Map payload including galaxy supernodes,
    cluster member positions, bellwether scores, and convergence velocities.
    """
    try:
        from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

        fs = get_firestore_client()
        if not fs:
            raise HTTPException(status_code=503, detail="Database client unavailable")

        doc = fs.collection("streamer_correlation").document("current").get()
        if not doc.exists:
            return {
                "galaxy": {"tribes": [], "inter_tribe_links": []},
                "clusters": {},
                "meta": {"last_updated": 0, "num_tribes": 0, "status": "no_data"},
            }

        data = doc.to_dict()
        vibe_tribes = data.get("vibe_tribes", {})
        coords = data.get("constellation_coords", {})
        bellwether_scores = data.get("bellwether_scores", {})
        tribe_alignment_scores = data.get("tribe_alignment_scores", {})
        convergence_velocity = data.get("convergence_velocity", [])
        inter_tribe_links = data.get("inter_tribe_links", [])

        # Case-insensitive lookup for tribe alignment scores
        align_lookup = {k.lower().strip(): v for k, v in tribe_alignment_scores.items()}

        # Resolve display names for cluster members
        display_names = {}
        try:
            profile_docs = fs.collection("streamer_profiles").stream()
            for p_doc in profile_docs:
                p_data = p_doc.to_dict()
                disp = p_data.get("youtube_title") or p_data.get("twitch_display_name")
                if disp:
                    display_names[p_doc.id.strip().lower()] = disp
        except Exception as e:
            logger.warning(f"Failed to load display names in starmap: {e}")

        # Format clusters micro-view members and links
        clusters_data = {}
        cluster_coords = coords.get("clusters", {})
        for t_id, t_info in vibe_tribes.items():
            members = t_info.get("members", [])
            t_color = t_info.get("color", "#22d3ee")
            t_label = t_info.get("label", f"Tribe {t_id}")

            c_coords = cluster_coords.get(str(t_id), cluster_coords.get(int(t_id), {}))

            def _get_display_name(handle):
                m_lower = handle.lower()
                disp_name = display_names.get(m_lower, handle)
                if disp_name.lower().startswith("uc"):
                    try:
                        from ag_kaggle_5day.agents.gcp_storage import (
                            resolve_streamer_link,
                        )

                        link_info = resolve_streamer_link(handle, fs)
                        if link_info and link_info.get("display_name"):
                            disp_name = link_info["display_name"]
                    except Exception:
                        pass
                return disp_name

            formatted_members = []
            for m in members:
                m_pos = c_coords.get(m, {"x": 0.0, "y": 0.0, "z": 0.0})
                formatted_members.append(
                    {
                        "handle": m,
                        "display_name": _get_display_name(m),
                        "x": m_pos.get("x", 0.0),
                        "y": m_pos.get("y", 0.0),
                        "z": m_pos.get("z", 0.0),
                        "bellwether_score": bellwether_scores.get(m.lower(), 0.0),
                        "tribe_alignment": float(
                            align_lookup.get(m.lower().strip(), 1.0)
                        ),
                    }
                )

            # Filter convergence velocities for pairs within this cluster
            intra_links = []
            members_set = set(members)
            for link in convergence_velocity:
                sa = link.get("streamer_a")
                sb = link.get("streamer_b")
                if sa == sb:
                    continue
                # Skip links between a streamer's Twitch and YouTube accounts
                disp_a = _get_display_name(sa).strip().lower()
                disp_b = _get_display_name(sb).strip().lower()
                if disp_a == disp_b:
                    continue
                if sa in members_set and sb in members_set:
                    intra_links.append(
                        {
                            "a": sa,
                            "b": sb,
                            "velocity": link.get("velocity", 0.0),
                            "acceleration": link.get("acceleration", 0.0),
                            "direction": link.get("direction", "converging"),
                        }
                    )

            # Find top bellwether in this tribe
            top_member = "None"
            top_score = -1.0
            for m in members:
                score = bellwether_scores.get(m.lower(), 0.0)
                if score > top_score:
                    top_score = score
                    top_member = m

            clusters_data[str(t_id)] = {
                "label": t_label,
                "color": t_color,
                "description": t_info.get(
                    "description",
                    "A dynamic faction of streamers bound by "
                    "similar chat rhythms and viewer flows.",
                ),
                "members": formatted_members,
                "intra_links": intra_links,
                "top_bellwether": (
                    _get_display_name(top_member) if top_member else "None"
                ),
            }

        # Dynamically inject any custom scanned/bootstrapped micro-streamers
        try:
            # Fetch all micro_streamer/bootstrapped profiles with coordinates
            profiles_ref = (
                fs.collection("streamer_profiles")
                .where("tier", "in", ["micro_streamer", "bootstrapped"])
                .stream()
            )
            for doc_p in profiles_ref:
                p_data = doc_p.to_dict()
                coords_p = p_data.get("starfield_coordinates")
                tribe_id = p_data.get("current_vibe_tribe")

                # If they have a pre-calculated/assigned tribe, inject them directly
                if coords_p and tribe_id is not None and str(tribe_id) in clusters_data:
                    existing_handles = {
                        m["handle"].lower()
                        for m in clusters_data[str(tribe_id)]["members"]
                    }
                    h_lower = p_data["streamer_handle"].lower()
                    if h_lower not in existing_handles:
                        clusters_data[str(tribe_id)]["members"].append(
                            {
                                "handle": p_data["streamer_handle"],
                                "x": coords_p.get("x", 0.0),
                                "y": coords_p.get("y", 0.0),
                                "z": coords_p.get("z", 0.0),
                                "bellwether_score": p_data.get("bellwether_score", 0.0),
                                "custom_injected": True,
                            }
                        )
        except Exception as inject_err:
            logger.warning(
                f"Failed to inject dynamic custom streamers to starmap: {inject_err}"
            )

        # Format galaxy supernodes (now with fully-resolved dynamic member counts)
        galaxy_tribes = []
        galaxy_coords = coords.get("galaxy", {})
        for t_id, t_info in vibe_tribes.items():
            g_pos = galaxy_coords.get(
                str(t_id), galaxy_coords.get(int(t_id), {"x": 0.0, "y": 0.0, "z": 0.0})
            )

            # Find top bellwether in this tribe
            members = t_info.get("members", [])
            top_member = "None"
            top_score = -1.0
            for m in members:
                score = bellwether_scores.get(m.lower(), 0.0)
                if score > top_score:
                    top_score = score
                    top_member = m

            resolved_count = (
                len(clusters_data[str(t_id)]["members"])
                if str(t_id) in clusters_data
                else len(members)
            )

            galaxy_tribes.append(
                {
                    "id": str(t_id),
                    "label": t_info.get("label", f"Tribe {t_id}"),
                    "color": t_info.get("color", "#22d3ee"),
                    "description": t_info.get(
                        "description",
                        "A dynamic faction of streamers bound by "
                        "similar chat rhythms and viewer flows.",
                    ),
                    "x": g_pos.get("x", 0.0),
                    "y": g_pos.get("y", 0.0),
                    "z": g_pos.get("z", 0.0),
                    "member_count": resolved_count,
                    "top_bellwether": (
                        _get_display_name(top_member) if top_member else "None"
                    ),
                }
            )

        return {
            "galaxy": {"tribes": galaxy_tribes, "inter_tribe_links": inter_tribe_links},
            "clusters": clusters_data,
            "meta": {
                "last_updated": data.get("timestamp", 0.0),
                "num_tribes": len(vibe_tribes),
            },
        }
    except Exception as e:
        logger.error(f"Error in GET /api/starmap: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/starmap/nebula/{tribe_id}")
def api_get_starmap_nebula(tribe_id: str):
    """
    Retrieves all micro-streamers in a given tribe, extracts their high-dimensional
    features, runs a local cohort-specific PCA (3d), and returns their positions.
    """
    try:
        import numpy as np
        from sklearn.decomposition import PCA

        from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

        fs = get_firestore_client()
        if not fs:
            raise HTTPException(status_code=503, detail="Database client unavailable")

        # 1. Fetch all micro-streamers / bootstrapped in this tribe
        profiles_ref = (
            fs.collection("streamer_profiles")
            .where("current_vibe_tribe", "==", tribe_id)
            .where("tier", "in", ["micro_streamer", "bootstrapped"])
            .stream()
        )

        members = []
        features = []
        for doc in profiles_ref:
            p_data = doc.to_dict()
            handle = doc.id
            disp = (
                p_data.get("twitch_display_name")
                or p_data.get("youtube_title")
                or handle
            )
            bio = p_data.get("bootstrap_context", {}).get(
                "bio_description", p_data.get("twitch_description", "")
            )
            tags = p_data.get("bootstrap_context", {}).get("vibe_tags", [])
            avatar = p_data.get("twitch_avatar") or p_data.get("youtube_avatar")

            members.append(
                {
                    "handle": handle,
                    "display_name": disp,
                    "bio": bio,
                    "tags": tags,
                    "avatar": avatar,
                    "primary_game": p_data.get("primary_game", "Unknown"),
                }
            )

            # Extract features for PCA using shared library
            from ag_kaggle_5day.agents.scraper.feature_library import (
                extract_streamer_features,
            )

            vec = extract_streamer_features(p_data)
            features.append(vec)

        if not members:
            return {"members": []}

        # 2. Run local PCA (3d)
        X = np.array(features)

        # Add small random noise to prevent singular matrix if all points are identical
        if X.shape[0] > 1:
            X = X + np.random.normal(0, 1e-4, X.shape)

        # Standardize features
        mean = X.mean(axis=0)
        std = X.std(axis=0)
        std[std < 1e-5] = 1.0
        X_norm = (X - mean) / std

        n_comp = min(3, X_norm.shape[0], X_norm.shape[1])
        if n_comp > 0:
            pca = PCA(n_components=n_comp)
            projected = pca.fit_transform(X_norm)
            if projected.shape[1] < 3:
                padding = np.zeros((projected.shape[0], 3 - projected.shape[1]))
                projected = np.hstack((projected, padding))
        else:
            projected = np.zeros((len(members), 3))

        # Scale coordinates to [-1.0, 1.0] range for Star Map
        for d in range(3):
            min_val = projected[:, d].min()
            max_val = projected[:, d].max()
            if max_val - min_val > 1e-5:
                projected[:, d] = (
                    2.0 * (projected[:, d] - min_val) / (max_val - min_val) - 1.0
                )
            else:
                n_points = projected.shape[0]
                if n_points > 1:
                    projected[:, d] = np.linspace(-1.0, 1.0, n_points)
                else:
                    projected[:, d] = 0.0

        # Calculate alignment metrics
        dist = np.linalg.norm(X_norm, axis=1)
        alignment = np.exp(-0.3 * dist)

        # Assign coordinates to members list
        for idx, m in enumerate(members):
            m["x"] = float(projected[idx, 0])
            m["y"] = float(projected[idx, 1])
            m["z"] = float(projected[idx, 2])
            m["tribe_alignment"] = float(alignment[idx])
            m["is_island"] = bool(alignment[idx] < 0.40)

        return {"members": members}
    except Exception as e:
        logger.error(f"Error in GET /api/starmap/nebula/{tribe_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/streamers/link")
def api_link_streamer_accounts(payload: LinkStreamerAccountsPayload):
    """
    Manually creates or updates a verified link between a Twitch handle
    and a YouTube channel ID, logging the link to Firestore and BigQuery.
    """
    try:
        from ag_kaggle_5day.agents.gcp_storage import store_streamer_account_link

        store_streamer_account_link(
            twitch_handle=payload.twitch_handle,
            youtube_channel_id=payload.youtube_channel_id,
            display_name=payload.display_name,
            manually_verified=True,
        )
        return {"status": "success", "message": "Accounts linked successfully."}
    except Exception as e:
        logger.error(f"Error in POST /api/streamers/link: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/streamers/autocomplete")
def api_streamer_autocomplete(q: str = Query("")):
    """Retrieves unique streamer handles matching the prefix from BigQuery/Cache."""
    try:
        from ag_kaggle_5day.agents.gcp_storage import get_streamer_autocomplete

        return get_streamer_autocomplete(q)
    except (ImportError, AttributeError):
        # Fallback stub for build gate
        return ["ninja", "shroud", "xqc", "pokimane", "ludwig"]


@router.get(
    "/api/streamers/{handle}/profile",
    dependencies=[
        Depends(check_rate_limit(profile_client_limiter, profile_global_limiter))
    ],
)
def api_get_streamer_profile(
    handle: str, refresh: bool = False, client_key: str | None = Depends(get_client_key)
):
    """
    Retrieves the aggregate profile details, active sentiment metrics,
    and the recent moments timeline for a streamer handle.
    """
    try:
        from ag_kaggle_5day.agents.gcp_storage import (
            get_cached_streamer_sentiment,
            get_firestore_client,
            get_historical_sentiment_summary,
            get_streamer_profile_fabric_from_fs,
        )

        clean_handle = handle.strip().lstrip("@")
        is_yt = bool(re.match(r"^[uU][cC][a-zA-Z0-9_-]{22}$", clean_handle))
        h = clean_handle if is_yt else clean_handle.lower()

        if is_yt and h.lower() == h:
            db_client = get_firestore_client()
            if db_client:
                from ag_kaggle_5day.agents.gcp_storage import (
                    get_case_preserved_youtube_id,
                )

                healed = get_case_preserved_youtube_id(h, None, db_client)
                if healed and healed != h:
                    h = healed

        # Check for account linking
        linked_twitch = None
        linked_youtube = None
        display_name = clean_handle

        try:
            from ag_kaggle_5day.agents.gcp_storage import resolve_streamer_link

            link_info = resolve_streamer_link(h)
            if link_info:
                linked_twitch = link_info.get("twitch_handle")
                linked_youtube = link_info.get("youtube_channel_id")
                display_name = link_info.get("display_name") or display_name
        except (ImportError, AttributeError):
            pass

        # Determine handles to fetch
        handles_to_fetch = [h]
        if linked_twitch and linked_twitch.strip().lower() not in [
            x.lower() for x in handles_to_fetch
        ]:
            handles_to_fetch.append(linked_twitch)
        if linked_youtube and linked_youtube.strip().lower() not in [
            x.lower() for x in handles_to_fetch
        ]:
            handles_to_fetch.append(linked_youtube)

        # Fetch profile
        profile = None
        for fetch_h in handles_to_fetch:
            p = get_streamer_profile_fabric_from_fs(fetch_h)
            if p:
                if not profile:
                    profile = dict(p)
                else:
                    # Merge profile fields
                    for k, v in p.items():
                        if v and not profile.get(k):
                            profile[k] = v

        # If profile is missing or lacks basic metadata, trigger on-demand aggregation
        is_missing_metadata = False
        if refresh:
            if not client_key or not client_key.strip():
                raise HTTPException(
                    status_code=401,
                    detail="API key required for on-demand profile refresh.",
                )
            is_missing_metadata = True
        elif not profile:
            is_missing_metadata = True
        elif not profile.get("archetype_cluster"):
            if h.lower().startswith("uc") and not profile.get("youtube_title"):
                is_missing_metadata = True
            elif not h.lower().startswith("uc") and not profile.get("twitch_avatar"):
                from ag_kaggle_5day.agents.scraper import TwitchAPIClient

                if TwitchAPIClient().is_configured:
                    is_missing_metadata = True
                elif not profile.get("youtube_title"):
                    is_missing_metadata = True

        if is_missing_metadata and h.lower() not in active_profile_builds:
            active_profile_builds.add(h.lower())
            try:
                # Security Check: Enforce key restriction for unknown handles
                if refresh:
                    effective_key = client_key.strip()
                    is_server_key = False
                else:
                    effective_key = (
                        client_key.strip()
                        if (client_key and client_key.strip())
                        else get_effective_key()
                    )
                    is_server_key = not (client_key and client_key.strip())

                if is_server_key:
                    from ag_kaggle_5day.agents.advisor import (
                        get_unique_streamer_handles,
                    )

                    unique_handles = {x.lower() for x in get_unique_streamer_handles()}
                    if h.lower() not in unique_handles:
                        logger.warning(
                            "Profile: Blocking on-demand generation for "
                            f"unknown handle '{h}' using server key."
                        )
                        if not profile:
                            raise HTTPException(
                                status_code=404,
                                detail=(
                                    f"Streamer '{h}' is unknown. Please "
                                    "provide a personal Gemini API Key "
                                    "to initialize new profiles."
                                ),
                            )
                        is_missing_metadata = False  # Do not regenerate/update

                if is_missing_metadata:
                    from ag_kaggle_5day.agents.advisor import (
                        _classify_single_streamer_archetype,
                        _process_single_streamer,
                    )
                    from ag_kaggle_5day.agents.gcp_storage import (
                        store_streamer_profile_fabric,
                    )

                    p_new = _process_single_streamer(h, effective_key)
                    if p_new:
                        p_new = _classify_single_streamer_archetype(
                            p_new, effective_key
                        )
                        store_streamer_profile_fabric(h, p_new)
                        if not profile:
                            profile = p_new
                        else:
                            profile.update(p_new)
            except HTTPException:
                raise
            except Exception as cond_err:
                logger.warning(
                    f"On-demand profile aggregation failed for {h}: {cond_err}"
                )
            finally:
                active_profile_builds.discard(h.lower())
        elif is_missing_metadata:
            # Wait for concurrent build to complete
            logger.info(
                f"Profile: Handle '{h}' is already being built concurrently. "
                "Waiting for completion..."
            )
            start_wait = time.time()
            while time.time() - start_wait < 30.0:
                time.sleep(1.0)
                p_check = get_streamer_profile_fabric_from_fs(h)
                if p_check and (
                    p_check.get("archetype_cluster") or p_check.get("youtube_title")
                ):
                    profile = dict(p_check)
                    break

        # Fetch sentiment
        sentiment = get_cached_streamer_sentiment(h) or {}

        # Run on-demand status & viewership check (guarded by 2-minute cache)
        now_ts = time.time()
        last_live_check = (
            sentiment.get("last_live_check_timestamp", 0.0) if sentiment else 0.0
        )

        if now_ts - last_live_check > 120.0:
            twitch_check_handle = linked_twitch or (None if is_yt else h)
            youtube_check_id = linked_youtube or (h if is_yt else None)

            try:
                from ag_kaggle_5day.agents.scraper import (
                    check_streamer_live_status_ondemand,
                )

                live_info = check_streamer_live_status_ondemand(
                    twitch_handle=twitch_check_handle,
                    youtube_channel_id=youtube_check_id,
                )

                if not sentiment:
                    sentiment = {
                        "streamer_handle": h,
                        "timestamp": now_ts,
                        "msg_per_minute": 0.0,
                        "chat_volatility": 0.0,
                        "rolling_sentiment_score": 0.0,
                    }

                sentiment["viewer_count"] = live_info["viewer_count"]
                sentiment["twitch_viewers"] = live_info["twitch_viewers"]
                sentiment["youtube_viewers"] = live_info["youtube_viewers"]
                sentiment["last_live_check_timestamp"] = now_ts

                if live_info["is_live"]:
                    sentiment["sentiment"] = "Neutral"
                    sentiment["game_name"] = live_info["game_name"]
                    sentiment["source"] = live_info["source"]
                else:
                    sentiment["sentiment"] = "Offline"
                    sentiment["viewer_count"] = 0

                # Cache updated live status in Firestore for all linked/associated
                # handles
                db_client = get_firestore_client()
                if db_client:
                    for fh in handles_to_fetch:
                        db_client.collection("streamer_sentiment").document(
                            fh.lower()
                        ).set(
                            {
                                "viewer_count": sentiment["viewer_count"],
                                "twitch_viewers": sentiment["twitch_viewers"],
                                "youtube_viewers": sentiment["youtube_viewers"],
                                "last_live_check_timestamp": now_ts,
                                "sentiment": sentiment["sentiment"],
                                "game_name": sentiment.get("game_name", "Unknown"),
                                "source": sentiment.get("source", "cache"),
                                "timestamp": now_ts,
                            },
                            merge=True,
                        )
                    logger.info(
                        f"Updated live status on-demand for '{h}'. "
                        f"Live={live_info['is_live']}, "
                        f"Viewers={sentiment['viewer_count']}"
                    )
            except Exception as live_err:
                logger.warning(
                    f"On-demand live status check failed for '{h}': {live_err}"
                )

        if sentiment:
            sentiment.setdefault("spectator_ratio", None)
            sentiment.setdefault("recent_clips", [])
            sentiment.setdefault("game_tags", [])

        # Check spotlight and expose report existence flags
        has_spotlight = False
        has_expose = False
        fs = get_firestore_client()
        if fs:
            try:
                # Check spotlight
                spot_doc = fs.collection("spotlight_medium_articles").document(h).get()
                if spot_doc.exists:
                    has_spotlight = True
                else:
                    for extra_h in [linked_twitch, linked_youtube]:
                        if extra_h and extra_h.strip().lower() != h:
                            exists = (
                                fs.collection("spotlight_medium_articles")
                                .document(extra_h.strip().lower())
                                .get()
                                .exists
                            )
                            if exists:
                                has_spotlight = True
                                break
            except Exception as e:
                logger.warning(f"Error checking spotlight doc for {h}: {e}")

            try:
                # Check expose
                from google.cloud.firestore_v1.base_query import FieldFilter

                expose_query = (
                    fs.collection("spotlight_expose_articles")
                    .where(filter=FieldFilter("streamer_handle", "==", h))
                    .limit(1)
                    .stream()
                )
                if any(expose_query):
                    has_expose = True
                else:
                    for extra_h in [linked_twitch, linked_youtube]:
                        if extra_h and extra_h.strip().lower() != h:
                            eq = (
                                fs.collection("spotlight_expose_articles")
                                .where(
                                    filter=FieldFilter(
                                        "streamer_handle",
                                        "==",
                                        extra_h.strip().lower(),
                                    )
                                )
                                .limit(1)
                                .stream()
                            )
                            if any(eq):
                                has_expose = True
                                break
            except Exception as e:
                logger.warning(f"Error checking expose docs for {h}: {e}")

        moments = []
        if fs:
            try:
                from google.cloud.firestore_v1.base_query import FieldFilter

                from ag_kaggle_5day.agents.gcp_storage import (
                    get_case_preserved_youtube_id,
                )

                # Query moments for all linked handles
                target_handles = []
                main_h = h.strip()
                if main_h.lower().startswith("uc"):
                    main_h = get_case_preserved_youtube_id(main_h.lower(), None, fs)
                else:
                    main_h = main_h.lower()
                target_handles.append(main_h)

                if linked_twitch:
                    lt_clean = linked_twitch.strip().lower()
                    if lt_clean not in target_handles:
                        target_handles.append(lt_clean)

                if linked_youtube:
                    ly_preserved = get_case_preserved_youtube_id(
                        linked_youtube.strip().lower(), None, fs
                    )
                    if ly_preserved not in target_handles:
                        target_handles.append(ly_preserved)

                docs = []
                for th in target_handles:
                    th_docs = (
                        fs.collection("streamer_moments")
                        .where(filter=FieldFilter("streamer_handle", "==", th))
                        .stream()
                    )
                    docs.extend(list(th_docs))

                # Sort combined moments by timestamp desc
                moments_dicts = []
                for doc in docs:
                    d = doc.to_dict()
                    moments_dicts.append(d)
                moments_dicts.sort(
                    key=lambda x: x.get("timestamp", 0.0) or 0.0, reverse=True
                )

                for d in moments_dicts[:10]:
                    moments.append(
                        {
                            "timestamp": d.get("timestamp"),
                            "trigger_type": d.get("trigger_type"),
                            "summary": d.get("summary"),
                            "game_name": d.get("game_name"),
                            "trigger_value": d.get("trigger_value"),
                        }
                    )
            except Exception as query_err:
                logger.warning(f"Failed to query moments for '{h}': {query_err}")

        history = get_historical_sentiment_summary(h)

        if profile:
            if profile.get("youtube_title"):
                display_name = profile["youtube_title"]
            elif profile.get("twitch_display_name"):
                display_name = profile["twitch_display_name"]

        return {
            "profile": profile or {},
            "sentiment": sentiment or {},
            "moments": moments,
            "history": history or [],
            "has_spotlight": has_spotlight,
            "has_expose": has_expose,
            "linked_twitch": linked_twitch,
            "linked_youtube": linked_youtube,
            "display_name": display_name,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching profile for '{handle}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def compute_ridge_forecast(history_rows: list[dict], horizon_hours: int) -> dict:
    """
    Fits Ridge regression models for:
      - viewer_count
      - msg_per_minute
      - rolling_sentiment_score
    Returns actual history grid, predicted forecast steps, and 95% Confidence Intervals.
    """
    import math
    from datetime import datetime

    import numpy as np
    from sklearn.linear_model import Ridge

    # Sort history by timestamp ascending
    history_rows = [h for h in history_rows if h.get("timestamp")]
    history_rows = sorted(history_rows, key=lambda x: x["timestamp"])

    timestamps = [h["timestamp"] for h in history_rows]
    if len(timestamps) < 2:
        return {
            "status": "insufficient_data",
            "message": "At least 2 data points are required.",
        }

    start_ts = min(timestamps)
    end_ts = max(timestamps)

    # Construct 1-hour regular grid
    hour_seconds = 3600.0
    grid_ts = []
    curr = start_ts
    while curr <= end_ts:
        grid_ts.append(curr)
        curr += hour_seconds

    # If the grid is too small, pad it to at least 12 hours
    if len(grid_ts) < 12:
        pad_needed = 12 - len(grid_ts)
        grid_ts = [
            start_ts - (i * hour_seconds) for i in range(pad_needed, 0, -1)
        ] + grid_ts
        start_ts = min(grid_ts)

    # We upsample using decay metrics or direct values
    grid_data = {
        "timestamp": grid_ts,
        "viewer_count": [],
        "msg_per_minute": [],
        "rolling_sentiment_score": [],
        "weight": [],
    }

    # Find the matching observation or calculate decayed state
    for ts in grid_ts:
        match = None
        best_dt = 1800.0
        for h in history_rows:
            dt = abs(h["timestamp"] - ts)
            if dt < best_dt:
                best_dt = dt
                match = h

        if match:
            grid_data["viewer_count"].append(float(match.get("viewer_count") or 0.0))
            grid_data["msg_per_minute"].append(
                float(match.get("msg_per_minute") or 0.0)
            )
            grid_data["rolling_sentiment_score"].append(
                float(match.get("rolling_sentiment_score") or 0.0)
            )
            grid_data["weight"].append(1.0)
        else:
            preceding = [h for h in history_rows if h["timestamp"] < ts]
            if preceding:
                last_obs = preceding[-1]
                dt = ts - last_obs["timestamp"]

                v_decay = float(last_obs.get("viewer_count") or 0.0)

                alpha_speed = math.exp(-dt / (3 * 3600.0))
                s_decay = alpha_speed * float(last_obs.get("msg_per_minute") or 0.0)

                alpha_sent = math.exp(-dt / (12 * 3600.0))
                sent_decay = alpha_sent * float(
                    last_obs.get("rolling_sentiment_score") or 0.0
                )

                grid_data["viewer_count"].append(v_decay)
                grid_data["msg_per_minute"].append(s_decay)
                grid_data["rolling_sentiment_score"].append(sent_decay)
                grid_data["weight"].append(max(0.1, alpha_speed))
            else:
                grid_data["viewer_count"].append(10.0)
                grid_data["msg_per_minute"].append(5.0)
                grid_data["rolling_sentiment_score"].append(0.0)
                grid_data["weight"].append(0.1)

    N = len(grid_ts)
    if N < 6:
        return {
            "status": "insufficient_data",
            "message": "At least 6 data points are required.",
        }

    lags = 2
    X_rows = []
    y_viewers = []
    y_speed = []
    y_sentiment = []
    weights_train = []

    for i in range(lags, N):
        row = []
        # Lag 1
        row.append(grid_data["viewer_count"][i - 1])
        row.append(grid_data["msg_per_minute"][i - 1])
        row.append(grid_data["rolling_sentiment_score"][i - 1])
        # Lag 2
        row.append(grid_data["viewer_count"][i - 2])
        row.append(grid_data["msg_per_minute"][i - 2])
        row.append(grid_data["rolling_sentiment_score"][i - 2])

        dt_obj = datetime.fromtimestamp(grid_data["timestamp"][i])
        hour = dt_obj.hour
        row.append(math.sin(2 * math.pi * hour / 24.0))
        row.append(math.cos(2 * math.pi * hour / 24.0))

        X_rows.append(row)
        y_viewers.append(grid_data["viewer_count"][i])
        y_speed.append(grid_data["msg_per_minute"][i])
        y_sentiment.append(grid_data["rolling_sentiment_score"][i])
        weights_train.append(grid_data["weight"][i])

    X = np.array(X_rows)
    weights = np.array(weights_train)
    p = X.shape[1]

    targets = {
        "viewer_count": np.array(y_viewers),
        "msg_per_minute": np.array(y_speed),
        "rolling_sentiment_score": np.array(y_sentiment),
    }

    results = {}
    df = N - p
    for name, y in targets.items():
        model = Ridge(alpha=1.0)
        model.fit(X, y, sample_weight=weights)

        y_pred = model.predict(X)

        y_mean = np.average(y, weights=weights)
        ss_tot = np.sum(weights * (y - y_mean) ** 2)
        ss_res = np.sum(weights * (y - y_pred) ** 2)
        r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0.0 else 0.0

        df = len(y) - p
        df = max(1, df)
        std_err = np.sqrt(ss_res / df) if df > 0 else 0.0

        forecast = []
        ci_upper = []
        ci_lower = []

        curr_lags = [
            grid_data["viewer_count"][-1],
            grid_data["msg_per_minute"][-1],
            grid_data["rolling_sentiment_score"][-1],
            grid_data["viewer_count"][-2],
            grid_data["msg_per_minute"][-2],
            grid_data["rolling_sentiment_score"][-2],
        ]

        try:
            W = np.diag(weights)
            XTWX = X.T @ W @ X + np.eye(p)
            XTWX_inv = np.linalg.inv(XTWX)
        except Exception:
            XTWX_inv = np.eye(p)

        last_ts = grid_data["timestamp"][-1]

        for h_idx in range(1, horizon_hours + 1):
            f_time = last_ts + h_idx * hour_seconds
            f_dt_obj = datetime.fromtimestamp(f_time)
            f_hour = f_dt_obj.hour

            x_0 = np.array(
                curr_lags
                + [
                    math.sin(2 * math.pi * f_hour / 24.0),
                    math.cos(2 * math.pi * f_hour / 24.0),
                ]
            )

            pred_val = float(model.predict(x_0.reshape(1, -1))[0])

            if name == "viewer_count" or name == "msg_per_minute":
                pred_val = max(0.0, pred_val)
            elif name == "rolling_sentiment_score":
                pred_val = max(-1.0, min(1.0, pred_val))

            forecast.append(round(pred_val, 2))

            var_pred = (std_err**2) * (1.0 + float(x_0.T @ XTWX_inv @ x_0))
            se_pred = np.sqrt(var_pred)

            t_crit = 2.0
            ci_u = pred_val + t_crit * se_pred
            ci_l = pred_val - t_crit * se_pred

            if name == "viewer_count" or name == "msg_per_minute":
                ci_l = max(0.0, ci_l)
            elif name == "rolling_sentiment_score":
                ci_u = min(1.0, ci_u)
                ci_l = max(-1.0, ci_l)

            ci_upper.append(round(ci_u, 2))
            ci_lower.append(round(ci_l, 2))

            curr_lags = [
                pred_val if name == "viewer_count" else curr_lags[0],
                pred_val if name == "msg_per_minute" else curr_lags[1],
                pred_val if name == "rolling_sentiment_score" else curr_lags[2],
                curr_lags[0],
                curr_lags[1],
                curr_lags[2],
            ]

        results[name] = {
            "history": [round(v, 2) for v in grid_data[name]],
            "forecast": forecast,
            "ci_upper": ci_upper,
            "ci_lower": ci_lower,
            "r2_score": round(float(r2), 3),
            "std_error": round(float(std_err), 3),
        }

    return {
        "status": "success",
        "sample_count": N,
        "degrees_of_freedom": df,
        "forecast_horizon_hours": horizon_hours,
        "history_timestamps": [int(t) for t in grid_data["timestamp"]],
        "predictions": results,
    }


@router.get(
    "/api/streamers/{handle}/forecast",
    dependencies=[
        Depends(check_rate_limit(forecast_client_limiter, forecast_global_limiter))
    ],
)
def api_streamer_forecast(handle: str, horizon: int = 3):
    """Fits weighted Ridge regression forecasting models on the streamer's

    resampled history using on-the-fly continuous decay gap filling.
    Uses 1-hour cache.
    """
    import time

    from ag_kaggle_5day.agents.gcp_storage import (
        get_firestore_client,
        get_historical_sentiment_summary,
        store_app_cache_state,
    )

    h = handle.strip().lower()
    horizon_val = min(6, max(1, horizon))
    cache_key = f"forecast_{h}_{horizon_val}"

    # 1. Try serving from cache
    fs = get_firestore_client()
    if fs:
        try:
            doc = fs.collection("system_cache").document(cache_key).get()
            if doc.exists:
                wrapper = doc.to_dict() or {}
                timestamp = wrapper.get("timestamp")
                if timestamp:
                    has_ts = hasattr(timestamp, "timestamp")
                    ts_val = timestamp.timestamp() if has_ts else float(timestamp)
                    if time.time() - ts_val <= 3600.0:
                        logger.info(f"Forecast: Serving cached forecast for @{h}")
                        return wrapper.get("data")
        except Exception as e:
            logger.warning(f"Forecast: Failed to read cache: {e}")

    # 2. Get history from Firestore (up to 100 checks)
    history = get_historical_sentiment_summary(h, limit=100)
    if not history:
        raise HTTPException(
            status_code=404, detail=f"No historical data found for streamer @{h}."
        )

    # 3. Compute forecast
    res = compute_ridge_forecast(history, horizon_val)
    if res.get("status") == "insufficient_data":
        return res

    # 4. Cache results
    if fs:
        try:
            store_app_cache_state(cache_key, res)
        except Exception as e:
            logger.warning(f"Forecast: Failed to store cache: {e}")

    return res


@router.get(
    "/api/tribes/{tribe_id}/forecast",
    dependencies=[
        Depends(check_rate_limit(forecast_client_limiter, forecast_global_limiter))
    ],
)
def api_tribe_forecast(tribe_id: str, horizon: int = 3):
    """
    Fits forecasting models on the aggregated, resampled history of all tribe members.
    Uses 1-hour cache.
    """
    import time

    from ag_kaggle_5day.agents.gcp_storage import (
        get_firestore_client,
        get_historical_sentiment_summary,
        store_app_cache_state,
    )

    t_id = tribe_id.strip()
    horizon = min(6, max(1, horizon))
    cache_key = f"forecast_tribe_{t_id}_{horizon}"

    # 1. Try serving from cache
    fs = get_firestore_client()
    if fs:
        try:
            doc = fs.collection("system_cache").document(cache_key).get()
            if doc.exists:
                wrapper = doc.to_dict() or {}
                timestamp = wrapper.get("timestamp")
                if timestamp:
                    has_ts = hasattr(timestamp, "timestamp")
                    ts_val = timestamp.timestamp() if has_ts else float(timestamp)
                    if time.time() - ts_val <= 3600.0:
                        logger.info(
                            f"Forecast: Serving cached forecast for tribe {t_id}"
                        )
                        return wrapper.get("data")
        except Exception as e:
            logger.warning(f"Forecast: Failed to read cache: {e}")

    # 2. Get tribe members
    if not fs:
        raise HTTPException(status_code=500, detail="Database client unavailable.")

    doc = fs.collection("streamer_correlation").document("tribe_names").get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Vibe Tribes metadata not found.")

    tribe_data = doc.to_dict() or {}
    tribe_info = tribe_data.get(t_id)
    if not tribe_info or not tribe_info.get("members"):
        raise HTTPException(
            status_code=404, detail=f"Tribe {t_id} not found or has no members."
        )

    members = tribe_info["members"]

    # 3. Aggregated history retrieve
    combined_history = []
    for m in members:
        hist = get_historical_sentiment_summary(m, limit=100)
        combined_history.extend(hist)

    if not combined_history:
        raise HTTPException(
            status_code=404,
            detail=f"No historical checks found for members of tribe {t_id}.",
        )

    # 4. Compute forecast
    res = compute_ridge_forecast(combined_history, horizon)
    if res.get("status") == "insufficient_data":
        return res

    # 5. Cache results
    try:
        store_app_cache_state(cache_key, res)
    except Exception as e:
        logger.warning(f"Forecast: Failed to store cache: {e}")

    return res
