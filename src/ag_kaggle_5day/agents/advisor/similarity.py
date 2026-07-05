from __future__ import annotations

import datetime
import logging

logger = logging.getLogger("streamer_advisor.advisor")


def get_viewer_count_for_handle(handle: str) -> int:
    """Helper to get last-known viewer count for a streamer handle from cached games."""
    try:
        from ag_kaggle_5day.agents.advisor import get_cached_games

        for g in get_cached_games():
            for s in g.get("top_streamers", []):
                if s.get("user_login", "").lower() == handle.lower():
                    return int(s.get("viewer_count", 0))
    except Exception:
        pass
    return 0


def get_circular_time_distance(time_a: str, time_b: str) -> float:
    """Computes adjacent distance on a 24h clock for active bins."""
    time_map = {"morning": 0.0, "afternoon": 90.0, "evening": 180.0, "latenight": 270.0}
    angle_a = time_map.get(time_a.lower(), 180.0)
    angle_b = time_map.get(time_b.lower(), 180.0)
    diff = abs(angle_a - angle_b)
    if diff > 180.0:
        diff = 360.0 - diff
    return diff / 180.0


def get_jaccard_overlap(list_a: list, list_b: list) -> float:
    """Calculates Jaccard similarity coefficient between two sets of games."""
    set_a = set(g.strip().lower() for g in list_a if g)
    set_b = set(g.strip().lower() for g in list_b if g)
    if not set_a or not set_b:
        return 0.0
    return len(set_a.intersection(set_b)) / len(set_a.union(set_b))


def get_sentiment_ratios_for_handle(handle: str) -> tuple[float, float, float, float]:
    """Retrieves high-fidelity positive, mixed, negative, neutral

    sentiment ratios from BQ.
    """
    from ag_kaggle_5day.agents.gcp_storage import get_historical_sentiment_summary

    try:
        history = get_historical_sentiment_summary(handle, limit=20)
        if history:
            sents = [
                c.get("sentiment")
                for c in history
                if c.get("sentiment") and c.get("sentiment") != "Offline"
            ]
            if sents:
                total = len(sents)
                pos = sents.count("Positive") / total
                mix = sents.count("Mixed") / total
                neg = sents.count("Negative") / total
                neu = sents.count("Neutral") / total
                return pos, mix, neg, neu
    except Exception:
        pass
    return (0.25, 0.5, 0.15, 0.1)


def calculate_similarity_nvar(
    profile_a: dict, profile_b: dict
) -> tuple[float, dict, str]:
    """Calculates non-linear similarity score between two streamer

    profiles using NVAR combinations.
    """
    import math

    handle_a = profile_a["streamer_handle"]
    handle_b = profile_b["streamer_handle"]

    # 1. Circular Time Distance
    time_a = profile_a.get("time_active_cluster", "evening")
    time_b = profile_b.get("time_active_cluster", "evening")
    time_dist = get_circular_time_distance(time_a, time_b)

    # 2. Audience Engagement Density
    vel_a = profile_a.get("average_msg_per_minute", 0.0) or profile_a.get(
        "msg_per_minute", 0.0
    )
    vel_b = profile_b.get("average_msg_per_minute", 0.0) or profile_b.get(
        "msg_per_minute", 0.0
    )
    viewers_a = get_viewer_count_for_handle(handle_a)
    viewers_b = get_viewer_count_for_handle(handle_b)

    density_a = vel_a / math.log(math.e + viewers_a)
    density_b = vel_b / math.log(math.e + viewers_b)
    density_diff = abs(density_a - density_b)
    density_prox = 1.0 / (1.0 + 0.05 * density_diff)

    # 3. Sentiment Polarization Ratio
    pos_a, mix_a, neg_a, _ = get_sentiment_ratios_for_handle(handle_a)
    pos_b, mix_b, neg_b, _ = get_sentiment_ratios_for_handle(handle_b)

    pol_a = (pos_a + mix_a + 0.01) / (neg_a + 0.01)
    pol_b = (pos_b + mix_b + 0.01) / (neg_b + 0.01)
    pol_diff = abs(pol_a - pol_b)
    pol_prox = 1.0 / (1.0 + 0.2 * pol_diff)

    # 4. Variety Jaccard Overlap
    games_a = profile_a.get("top_games", [])
    games_b = profile_b.get("top_games", [])
    jaccard = get_jaccard_overlap(games_a, games_b)

    # 4b. Language Soft-Bias Index
    from ag_kaggle_5day.agents.scraper.feature_library import normalize_language_code

    lang_a_raw = profile_a.get("language") or "en"
    lang_b_raw = profile_b.get("language") or "en"
    langs_a = [lang_a_raw] if isinstance(lang_a_raw, str) else list(lang_a_raw)
    langs_b = [lang_b_raw] if isinstance(lang_b_raw, str) else list(lang_b_raw)
    langs_a = [normalize_language_code(x) for x in langs_a if isinstance(x, str)]
    langs_b = [normalize_language_code(x) for x in langs_b if isinstance(x, str)]
    if not langs_a:
        langs_a = ["en"]
    if not langs_b:
        langs_b = ["en"]
    union_langs = set(langs_a).union(set(langs_b))
    intersection_langs = set(langs_a).intersection(set(langs_b))
    jaccard_lang = len(intersection_langs) / len(union_langs) if union_langs else 0.0
    bridge_bonus = 0.05 if ("en" in langs_a or "en" in langs_b) else 0.0
    lang_similarity = min(jaccard_lang + bridge_bonus, 1.0)
    lang_bias = lang_similarity * 0.20

    # Composite similarity score: weighted combination
    time_weight = 0.15
    density_weight = 0.25
    pol_weight = 0.25
    jaccard_weight = 0.35

    composite_score = (
        time_weight * (1.0 - time_dist)
        + density_weight * density_prox
        + pol_weight * pol_prox
        + jaccard_weight * jaccard
    )
    composite_score = min(composite_score + lang_bias, 1.0)

    metrics = {
        "time_distance": time_dist,
        "engagement_density_diff": density_diff,
        "polarization_diff": pol_diff,
        "jaccard_overlap": jaccard,
        "language_bias": lang_bias,
    }

    whys = []
    if time_dist == 0.0:
        whys.append(f"both are active in the {time_a}")
    else:
        whys.append(f"active at different times ({time_a} vs {time_b})")

    if density_diff < 5.0:
        whys.append("have highly similar chat engagement density")
    else:
        whys.append(
            "differ in chat engagement density ("
            f"{round(density_a, 1)} vs {round(density_b, 1)} "
            "mpm/log-viewers)"
        )

    if pol_diff < 1.5:
        whys.append("have matching audience sentiment vibes")
    else:
        whys.append(
            "have different sentiment polarization ratios "
            f"({round(pol_a, 2)} vs {round(pol_b, 2)})"
        )

    if jaccard > 0.6:
        whys.append(
            "share a very high overlap of games ("
            f"{', '.join(set(games_a).intersection(set(games_b)))}"
            ")"
        )
    elif jaccard > 0.2:
        whys.append(
            "share some games like "
            f"{', '.join(list(set(games_a).intersection(set(games_b)))[:2])}"
        )
    else:
        whys.append("stream completely different game portfolios")

    if intersection_langs:
        whys.append(f"share language configurations ({', '.join(intersection_langs)})")

    why_str = f"Streamers {handle_a} and {handle_b}: " + ", ".join(whys) + "."

    return round(composite_score, 4), metrics, why_str


def get_similar_streamers(streamer_handle: str, top_n: int = 3) -> str:
    """Retrieves and formats a Markdown list of similar streamers for a given handle."""
    from ag_kaggle_5day.agents.gcp_storage import (
        get_firestore_client,
        get_streamer_profile_fabric_from_fs,
    )

    target_handle = streamer_handle.strip().lower()
    target_profile = get_streamer_profile_fabric_from_fs(target_handle)

    if not target_profile:
        return (
            f"Streamer profile for '{streamer_handle}' could not be "
            "found in the database."
        )

    peer_details = target_profile.get("peer_details", [])
    if peer_details:
        lines = [f"### Similarity Analysis for **{target_handle}**"]
        lines.append(
            "- **Archetype**: "
            f"{target_profile.get('archetype_cluster', 'Cozy_Social_Interactive')}"
        )
        lines.append(
            f"- **Primary Game**: {target_profile.get('primary_game', 'Variety')}"
        )
        lines.append("\nTop Similar Streamers:")
        for peer in peer_details[:top_n]:
            score_pct = int(peer.get("similarity", 0) * 100)
            lines.append(
                f"- **{peer['handle']}** ({score_pct}% Match)\n  - *Why*: {peer['why']}"
            )
        return "\n".join(lines)

    fs_client = get_firestore_client()
    if not fs_client:
        return "Firestore is unavailable. Cannot calculate similarity."

    try:
        docs = fs_client.collection("streamer_profiles").stream()
        all_profiles = []
        for doc in docs:
            p = doc.to_dict()
            handle = doc.id.lower()
            ts_doc = (
                fs_client.collection("streamer_analytics_timeseries")
                .document(handle)
                .get()
            )
            if ts_doc.exists:
                ts = ts_doc.to_dict()
                p["average_msg_per_minute"] = ts.get("average_msg_per_minute", 0.0)
            else:
                p["average_msg_per_minute"] = 0.0
            all_profiles.append(p)

        scored_peers = []
        for op in all_profiles:
            if op["streamer_handle"].lower() == target_handle:
                continue
            score, _, why = calculate_similarity_nvar(target_profile, op)
            scored_peers.append((op["streamer_handle"], score, why))

        scored_peers.sort(key=lambda x: x[1], reverse=True)

        lines = [
            f"### Similarity Analysis for **{target_handle}** (Dynamic Calculation)"
        ]
        lines.append(
            "- **Archetype**: "
            f"{target_profile.get('archetype_cluster', 'Cozy_Social_Interactive')}"
        )
        lines.append(
            f"- **Primary Game**: {target_profile.get('primary_game', 'Variety')}"
        )
        lines.append("\nTop Similar Streamers:")
        for peer in scored_peers[:top_n]:
            score_pct = int(peer[1] * 100)
            lines.append(f"- **{peer[0]}** ({score_pct}% Match)\n  - *Why*: {peer[2]}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error computing dynamic similarity report: {e}"


def get_similarity_drift(streamer_a: str, streamer_b: str) -> str:
    """Retrieves BigQuery similarity timeseries logs and formats a trajectory report."""
    from ag_kaggle_5day.agents.gcp_storage import get_similarity_drift_from_db

    sa = streamer_a.strip().lower()
    sb = streamer_b.strip().lower()

    drift_data = get_similarity_drift_from_db(sa, sb, limit_days=30)
    if not drift_data:
        return (
            f"### Similarity Drift Analysis: **{sa}** vs **{sb}**\n"
            "Note: No historical similarity records found in BigQuery "
            "(table is fresh or empty).\n\n"
            "**Mock Drift Trend Projection**:\n"
            "- 30 days ago: 85% similarity (both streaming competitive shooters)\n"
            "- 15 days ago: 78% similarity (streamer A variety shift)\n"
            "- Current: 68% similarity (streamer A doing cozy reacts, "
            "streamer B competitive sweat)\n\n"
            "*Status: Pairwise similarity logging enabled. "
            "Real trend points will populate as daily analytics run.*"
        )

    lines = [f"### Similarity Drift Analysis: **{sa}** vs **{sb}**"]
    lines.append(
        f"Found {len(drift_data)} historical data points over the last 30 days.\n"
    )

    first_point = drift_data[0]
    last_point = drift_data[-1]
    diff = last_point["similarity_score"] - first_point["similarity_score"]
    trend = "converged (increased)" if diff > 0 else "drifted apart (decreased)"

    lines.append(
        f"**Overall Trend**: Streamers have {trend} by "
        f"{abs(round(diff * 100, 1))}% similarity.\n"
    )
    lines.append("| Date | Similarity % | Jaccard Overlap | Why / Analysis |")
    lines.append("| --- | --- | --- | --- |")

    for pt in drift_data:
        dt_str = datetime.datetime.fromtimestamp(
            pt["timestamp"], datetime.timezone.utc
        ).strftime("%Y-%m-%d")
        score_pct = f"{int(pt['similarity_score'] * 100)}%"
        jaccard = f"{int(pt['game_jaccard_overlap'] * 100)}%"
        lines.append(
            f"| {dt_str} | {score_pct} | {jaccard} | {pt['why_explanation']} |"
        )

    return "\n".join(lines)


def get_streamer_comprehensive_dossier(streamer_handle: str) -> str:
    """Retrieves a comprehensive dossier for a streamer including profile fabric,
    peer similarity matches, and similarity drift trends for those matching peers.

    Args:
        streamer_handle: The name of the streamer (e.g. shroud).

    Returns:
        A beautifully formatted Markdown report containing all metrics and trends.
    """
    from ag_kaggle_5day.agents.advisor import get_streamer_correlations
    from ag_kaggle_5day.agents.gcp_storage import get_streamer_profile_fabric_from_fs

    target_handle = streamer_handle.strip().lower()
    profile = get_streamer_profile_fabric_from_fs(target_handle)

    if not profile:
        return (
            f"Streamer profile for '{streamer_handle}' "
            "could not be found in the database."
        )

    handle = profile.get("streamer_handle", streamer_handle)
    # 1. Start with the profile fabric details
    lines = [f"## Comprehensive Dossier for **{handle}**"]
    arch = profile.get("archetype_cluster", "Cozy_Social_Interactive")
    lines.append(f"- **Archetype Cluster**: {arch}")
    lines.append(f"- **Primary Game**: {profile.get('primary_game', 'Variety')}")
    lines.append(f"- **Time Active**: {profile.get('time_active_cluster', 'evening')}")
    lines.append(
        f"- **Profile Confidence**: {profile.get('fabric_status', 'preliminary')}"
    )

    top_games = ", ".join(profile.get("top_games", []))
    lines.append(f"- **Top Games Played**: {top_games if top_games else 'None'}")
    lines.append("")

    # 1.5 Add active telemetry from the cached sentiment document
    from ag_kaggle_5day.agents.gcp_storage import get_cached_streamer_sentiment

    sentiment = get_cached_streamer_sentiment(target_handle)
    if sentiment:
        lines.append("### Active Telemetry & Multi-Source Metrics")
        lines.append(
            f"- **Current Active Game**: {sentiment.get('game_name', 'Offline')}"
        )
        lines.append(
            f"- **Current Live Viewers**: {sentiment.get('viewer_count', 0):,}"
        )

        ratio = sentiment.get("spectator_ratio")
        if ratio is not None:
            lines.append(
                f"- **Steam Spectator Ratio**: {ratio:.4f} "
                "(Helix Viewers / Steam Active Players)"
            )

        tags = sentiment.get("game_tags", [])
        if tags:
            lines.append(f"- **Active Category Tags**: {', '.join(tags)}")

        clips = sentiment.get("recent_clips", [])
        if clips:
            lines.append("- **Featured Hype Clips**:")
            for c in clips:
                lines.append(
                    f"  - [{c.get('title')}]({c.get('url')}) "
                    f"({c.get('view_count', 0):,} views)"
                )
        lines.append("")

    # Fetch correlations for target handle
    res = get_streamer_correlations(target_handle)

    # 2. Add Vibe Tribe membership
    lines.append("### Vibe Tribe Membership")
    tribe = res.get("tribe_membership")
    if tribe:
        lines.append(
            f"- **Vibe Tribe**: {tribe['label']} (Tribe ID: {tribe['tribe_id']})"
        )
    else:
        lines.append("- **Vibe Tribe**: None / Unclassified")
    lines.append("")

    # 3. Add Bellwether Influence Rank
    lines.append("### Bellwether Influence Rank")
    bell_score = res.get("bellwether_score", 0.0)
    lines.append(f"- **Centrality Score**: {bell_score:.4f}")

    try:
        from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

        fs = get_firestore_client()
        if fs:
            doc = fs.collection("streamer_correlation").document("current").get()
            if doc.exists:
                b_scores = doc.to_dict().get("bellwether_scores", {})
                sorted_b = sorted(b_scores.items(), key=lambda x: x[1], reverse=True)
                rank = next(
                    (
                        idx + 1
                        for idx, (h, s) in enumerate(sorted_b)
                        if h == target_handle
                    ),
                    None,
                )
                if rank:
                    lines.append(
                        f"- **Ecosystem Rank**: {rank} of "
                        f"{len(b_scores)} active streamers"
                    )
    except Exception:
        pass
    lines.append("")

    # 4. Add Active Convergence Signals
    lines.append("### Active Convergence Signals")
    connections_with_velocity = [
        c
        for c in res.get("connections", [])
        if c.get("convergence_velocity", 0.0) > 0.0
    ]
    if connections_with_velocity:
        connections_with_velocity.sort(
            key=lambda x: x["convergence_velocity"], reverse=True
        )
        for conn in connections_with_velocity[:3]:
            dir_arrow = "▲" if conn["convergence_direction"] == "converging" else "▼"
            lines.append(
                f"- **{conn['streamer']}**: Correlation is {conn['convergence_direction']} "  # noqa: E501
                f"({dir_arrow} velocity: {conn['convergence_velocity']:.4f}/hr)"
            )
    else:
        lines.append("- No active convergence signals detected.")
    lines.append("")

    # 5. Add current peer similarities
    lines.append("### Current Peer Similarity Mappings")
    peer_details = profile.get("peer_details", [])
    if peer_details:
        for peer in peer_details[:3]:
            score_pct = int(peer.get("similarity", 0) * 100)
            lines.append(
                f"- **{peer['handle']}** ({score_pct}% Match)\n  - *Why*: {peer['why']}"
            )
    else:
        # Fallback to dynamic calculation if cache is missing
        lines.append(get_similar_streamers(target_handle, top_n=3))
    lines.append("")

    # 6. Add drift analysis for top peers
    lines.append("### Historical Similarity Drift for Top Peers")
    peers_list = [p["handle"] for p in peer_details[:3]] if peer_details else []

    if peers_list:
        for peer_handle in peers_list:
            lines.append(f"\n#### Drift Analysis: {handle} vs {peer_handle}")
            drift_report = get_similarity_drift(target_handle, peer_handle)
            lines.append(drift_report)
    else:
        lines.append(
            "No peer connections available to perform historical drift analysis."
        )

    return "\n".join(lines)
