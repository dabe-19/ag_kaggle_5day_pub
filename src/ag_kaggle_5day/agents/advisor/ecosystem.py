from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("streamer_advisor.advisor")


def get_streamer_correlations(
    streamer_handle: str, compare_with_handle: Optional[str] = None
) -> dict:
    """Reads the current streamer_correlation Firestore document and returns
    top correlated channels and comparison metrics.
    """
    from ag_kaggle_5day.agents.advisor import (
        get_circular_time_distance,
        get_jaccard_overlap,
    )
    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    target = streamer_handle.strip().lower()
    fs = get_firestore_client()
    if fs:
        try:
            from ag_kaggle_5day.agents.gcp_storage import resolve_streamer_link

            link_info = resolve_streamer_link(target, fs)
            if link_info:
                if link_info.get("twitch_handle"):
                    target = link_info["twitch_handle"].strip().lower()
                elif link_info.get("youtube_channel_id"):
                    from ag_kaggle_5day.agents.gcp_storage import (
                        get_case_preserved_youtube_id,
                    )

                    target = get_case_preserved_youtube_id(
                        link_info["youtube_channel_id"].strip().lower(), None, fs
                    )  # noqa: E501
        except Exception as resolve_err:
            logger.warning(
                f"Failed to resolve linked handle in correlations for {target}: {resolve_err}"  # noqa: E501
            )

    res = {
        "streamer_handle": target,
        "connections": [],
        "compare_score": None,
        "tribe_membership": None,
        "bellwether_score": 0.0,
    }

    if not fs:
        return res

    try:
        doc = fs.collection("streamer_correlation").document("current").get()
        if not doc.exists:
            return res

        import json

        data = doc.to_dict()
        streamers = data.get("streamers", [])
        matrices = {}
        if data.get("correlation_matrices_json"):
            try:
                matrices = json.loads(data["correlation_matrices_json"])
            except Exception as json_err:
                logger.error(
                    f"Failed to parse correlation_matrices_json in advisor: {json_err}"
                )
        if not matrices:
            matrices = data.get("correlation_matrices", {})
        bellwethers = data.get("bellwether_scores", {})
        tribes = data.get("vibe_tribes", {})
        velocities = data.get("convergence_velocity", [])

        if target not in streamers:
            return res

        target_idx = streamers.index(target)
        res["bellwether_score"] = bellwethers.get(target, 0.0)

        # Resolve target's tribe membership
        for t_id, t_info in tribes.items():
            if target in t_info.get("members", []):
                res["tribe_membership"] = {
                    "tribe_id": str(t_id),
                    "label": t_info.get("label"),
                    "color": t_info.get("color"),
                }
                break

        vol_matrix = matrices.get("chat_volatility", [])
        sent_matrix = matrices.get("rolling_sentiment_score", [])
        rate_matrix = matrices.get("msg_per_minute", [])

        def _get_val(matrix, t_idx, o_idx, o_handle):
            if isinstance(matrix, dict):
                row = matrix.get(o_handle, [])
                return row[t_idx] if t_idx < len(row) else 0.0
            elif isinstance(matrix, list):
                return (
                    matrix[t_idx][o_idx]
                    if t_idx < len(matrix) and o_idx < len(matrix[t_idx])
                    else 0.0
                )
            return 0.0

        # Pre-load profiles to calculate active hours and game Jaccard overlaps
        # efficiently
        all_profiles = {}
        try:
            docs = fs.collection("streamer_profiles").stream()
            for doc in docs:
                all_profiles[doc.id.strip().lower()] = doc.to_dict()
        except Exception as scan_err:
            logger.warning(
                f"Failed to pre-load profiles in get_streamer_correlations: {scan_err}"
            )

        scores = []
        target_profile = all_profiles.get(target, {})
        target_disp = (
            target_profile.get("youtube_title")
            or target_profile.get("twitch_display_name")
            or target
        )  # noqa: E501
        for idx, other in enumerate(streamers):
            if other == target:
                continue

            # Resolve other's display name
            other_disp = other
            other_prof = all_profiles.get(other.lower(), {})
            if other_prof:
                other_disp = (
                    other_prof.get("youtube_title")
                    or other_prof.get("twitch_display_name")
                    or other_prof.get("display_name")
                )

            is_uc = other.lower().startswith("uc")
            if (not other_disp or other_disp == other) and is_uc:
                try:
                    from ag_kaggle_5day.agents.gcp_storage import resolve_streamer_link

                    link_info_other = resolve_streamer_link(other, fs)
                    if link_info_other and link_info_other.get("display_name"):
                        other_disp = link_info_other["display_name"]
                except Exception:
                    pass

            if not other_disp:
                other_disp = other

            # Skip if other is just the other channel of the same streamer
            if other_disp.strip().lower() == target_disp.strip().lower():
                continue

            vol_corr = _get_val(vol_matrix, target_idx, idx, other)
            sent_corr = _get_val(sent_matrix, target_idx, idx, other)
            rate_corr = _get_val(rate_matrix, target_idx, idx, other)

            # Nuanced similarity computation: Incorporate active hours and game Jaccard
            # overlaps
            other_profile = all_profiles.get(other, {})

            # 1. Circular Time Distance Penalty
            time_a = target_profile.get("time_active_cluster", "evening")
            time_b = other_profile.get("time_active_cluster", "evening")
            time_dist = get_circular_time_distance(time_a, time_b)
            # Up to 40% penalty if broadcast times are opposite
            time_penalty = 1.0 - (time_dist * 0.4)

            # 2. Game Jaccard Overlap Boost
            games_a = target_profile.get("top_games", [])
            games_b = other_profile.get("top_games", [])
            jaccard = get_jaccard_overlap(games_a, games_b)
            jaccard_boost = jaccard * 0.2

            raw_average = (vol_corr + sent_corr + rate_corr) / 3.0

            # Scale and apply boosts/penalties keeping the correlation sign
            if raw_average >= 0.0:
                combined_score = raw_average * time_penalty + jaccard_boost
            else:
                combined_score = raw_average * time_penalty - jaccard_boost

            combined_score = max(-1.0, min(1.0, combined_score))

            # 3. Classify relationship tags
            if combined_score > 0.1:
                if vol_corr > 0.4 and jaccard > 0.2:
                    tag = "Hype-Aligned"
                elif sent_corr > 0.4 and time_dist < 0.2:
                    tag = "Vibe-Coupled"
                elif jaccard == 0.0:
                    tag = "Ecosystem-Parallel"
                else:
                    tag = "Co-trending"
            elif combined_score < -0.1:
                if vol_corr < -0.3:
                    tag = "Counter-Programmed"
                else:
                    tag = "Divergent"
            else:
                tag = "Co-trending" if combined_score >= 0.0 else "Divergent"

            # 4. Generate component reasons string
            reasons_parts = []
            if abs(vol_corr) > 0.25:
                direction = "shared" if vol_corr > 0.0 else "opposing"
                reasons_parts.append(f"{direction} chat volatility ({vol_corr:+.2f})")
            if abs(sent_corr) > 0.25:
                direction = "coupled" if sent_corr > 0.0 else "opposite"
                reasons_parts.append(f"{direction} sentiment ({sent_corr:+.2f})")
            if abs(rate_corr) > 0.25:
                direction = "similar" if rate_corr > 0.0 else "divergent"
                reasons_parts.append(f"{direction} chat speed ({rate_corr:+.2f})")
            if jaccard > 0.0:
                reasons_parts.append(f"shared games ({jaccard * 100:.0f}%)")
            if time_dist == 0.0:
                reasons_parts.append(f"active in {time_a}")

            reasons_str = (
                ", ".join(reasons_parts) if reasons_parts else "Parallel activity"
            )

            key = (target, other) if target < other else (other, target)
            vel_info = next(
                (
                    v
                    for v in velocities
                    if (v.get("streamer_a") == key[0] and v.get("streamer_b") == key[1])
                ),
                None,
            )

            # (other_disp resolved at top of loop)

            scores.append(
                {
                    "streamer": other,
                    "display_name": other_disp,
                    "volatility_corr": vol_corr,
                    "sentiment_corr": sent_corr,
                    "msg_rate_corr": rate_corr,
                    "combined_score": combined_score,
                    "tag": tag,
                    "reasons": reasons_str,
                    "convergence_velocity": vel_info.get("velocity", 0.0)
                    if vel_info
                    else 0.0,
                    "convergence_direction": vel_info.get("direction", "converging")
                    if vel_info
                    else "converging",
                }
            )

        # Separate positive vs negative connections
        pos_scores = [s for s in scores if s["combined_score"] > 0.0]
        neg_scores = [s for s in scores if s["combined_score"] <= 0.0]

        # Sort positive descending (strongest support)
        pos_scores.sort(key=lambda x: x["combined_score"], reverse=True)
        # Sort negative ascending (strongest opposition/most negative)
        neg_scores.sort(key=lambda x: x["combined_score"])

        res["connections"] = pos_scores[:3] + neg_scores[:3]
        res["supportive"] = pos_scores[:3]
        res["opposing"] = neg_scores[:3]

        if compare_with_handle:
            comp = compare_with_handle.strip().lower()
            if comp in streamers:
                comp_idx = streamers.index(comp)
                v_c = _get_val(vol_matrix, target_idx, comp_idx, comp)
                s_c = _get_val(sent_matrix, target_idx, comp_idx, comp)
                r_c = _get_val(rate_matrix, target_idx, comp_idx, comp)

                key_comp = (target, comp) if target < comp else (comp, target)
                vel_comp = next(
                    (
                        v
                        for v in velocities
                        if (
                            v.get("streamer_a") == key_comp[0]
                            and v.get("streamer_b") == key_comp[1]
                        )
                    ),
                    None,
                )

                res["compare_score"] = {
                    "volatility_corr": v_c,
                    "sentiment_corr": s_c,
                    "msg_rate_corr": r_c,
                    "combined_score": (v_c + s_c + r_c) / 3.0,
                    "convergence_velocity": vel_comp.get("velocity", 0.0)
                    if vel_comp
                    else 0.0,
                    "convergence_direction": vel_comp.get("direction", "converging")
                    if vel_comp
                    else "converging",
                }
    except Exception as e:
        logger.error(f"Error resolving streamer correlations: {e}")

    return res


def get_ecosystem_overview() -> str:
    """Retrieves an ecosystem-level overview of Vibe Tribes, top bellwethers,
    and active convergence alerts.
    """
    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    fs = get_firestore_client()
    if not fs:
        return "Database client unavailable."

    try:
        doc = fs.collection("streamer_correlation").document("current").get()
        if not doc.exists:
            return "No ecosystem analytics available yet. Please wait for the daily analytics job."  # noqa: E501

        data = doc.to_dict()
        vibe_tribes = data.get("vibe_tribes", {})
        bellwethers = data.get("bellwether_scores", {})
        velocities = data.get("convergence_velocity", [])

        lines = ["## Streamer Ecosystem Macro Overview"]

        # 1. Tribes Overview
        lines.append("\n### Detected Vibe Tribes")
        if vibe_tribes:
            for t_id, t_info in vibe_tribes.items():
                lines.append(
                    f"- **{t_info.get('label')}** (ID: {t_id}, Members: {t_info.get('member_count')}, "  # noqa: E501
                    f"Dominant Archetype: {t_info.get('dominant_archetype')})"
                )
        else:
            lines.append("No vibe tribes defined yet.")

        # 2. Top Bellwethers
        lines.append("\n### Top Bellwethers (Cultural Hubs)")
        if bellwethers:
            sorted_b = sorted(bellwethers.items(), key=lambda x: x[1], reverse=True)
            for idx, (h, s) in enumerate(sorted_b[:5]):
                lines.append(f"{idx + 1}. **{h}** (Centrality: {s:.4f})")
        else:
            lines.append("No bellwether scores calculated.")

        # 3. Top Convergence Alerts
        lines.append("\n### Active Convergence Alerts (Fastest Decoupling/Aligning)")
        if velocities:
            for idx, v in enumerate(velocities[:5]):
                dir_arrow = "▲" if v.get("direction") == "converging" else "▼"
                lines.append(
                    f"{idx + 1}. **{v.get('streamer_a')}** & **{v.get('streamer_b')}**: "  # noqa: E501
                    f"{v.get('direction')} ({dir_arrow} velocity: {v.get('velocity'):.4f}/hr)"  # noqa: E501
                )
        else:
            lines.append("No active convergence signals.")

        return "\n".join(lines)
    except Exception as e:
        return f"Error retrieving ecosystem overview: {e}"


def get_tribe_details(tribe_id: str) -> str:
    """Retrieves members, intra-cluster correlations, and convergence velocities
    for a specific Vibe Tribe.
    """
    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    fs = get_firestore_client()
    if not fs:
        return "Database client unavailable."

    try:
        doc = fs.collection("streamer_correlation").document("current").get()
        if not doc.exists:
            return "No ecosystem analytics available."

        data = doc.to_dict()
        vibe_tribes = data.get("vibe_tribes", {})
        bellwethers = data.get("bellwether_scores", {})
        tribe_alignment_scores = data.get("tribe_alignment_scores", {})
        velocities = data.get("convergence_velocity", [])

        t_id_str = str(tribe_id).strip()
        if t_id_str not in vibe_tribes:
            return f"Vibe Tribe '{tribe_id}' not found. Available IDs: {', '.join(vibe_tribes.keys())}"  # noqa: E501

        t_info = vibe_tribes[t_id_str]
        members = t_info.get("members", [])

        lines = [
            f"## Vibe Tribe Deep-Dive: **{t_info.get('label')}**",
            f"- **Tribe ID**: {t_id_str}",
            f"- **Member Count**: {len(members)}",
            f"- **Dominant Archetype**: {t_info.get('dominant_archetype')}",
            "",
            "### Tribe Members & Centrality Ranking",
        ]

        sorted_members = sorted(
            members, key=lambda m: bellwethers.get(m, 0.0), reverse=True
        )
        for idx, m in enumerate(sorted_members):
            score = bellwethers.get(m, 0.0)
            align_val = tribe_alignment_scores.get(m, 1.0)
            align_percent = align_val * 100
            is_island = align_val < 0.25
            island_tag = " [Island Outlier] 🏝️" if is_island else " [Core]"
            lines.append(
                f"- **{m}** (Centrality: {score:.4f} | "
                f"Alignment: {align_percent:.1f}%{island_tag})"
            )

        lines.append("\n### Active Convergence Signals (Within Tribe)")
        intra_velocities = []
        members_set = set(members)
        for v in velocities:
            sa = v.get("streamer_a")
            sb = v.get("streamer_b")
            if sa in members_set and sb in members_set:
                intra_velocities.append(v)

        if intra_velocities:
            for v in intra_velocities[:5]:
                dir_arrow = "▲" if v.get("direction") == "converging" else "▼"
                lines.append(
                    f"- **{v.get('streamer_a')}** & **{v.get('streamer_b')}**: "
                    f"{v.get('direction')} ({dir_arrow} velocity: {v.get('velocity'):.4f}/hr)"  # noqa: E501
                )
        else:
            lines.append("No active convergence signals inside this tribe.")

        return "\n".join(lines)
    except Exception as e:
        return f"Error retrieving tribe details: {e}"


def get_bellwether_rankings(top_n: int = 10) -> str:
    """Retrieves the ranked eigenvector centrality scores for all active streamers

    ecosystem-wide."""
    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    fs = get_firestore_client()
    if not fs:
        return "Database client unavailable."

    try:
        doc = fs.collection("streamer_correlation").document("current").get()
        if not doc.exists:
            return "No ecosystem analytics available."

        data = doc.to_dict()
        bellwethers = data.get("bellwether_scores", {})
        vibe_tribes = data.get("vibe_tribes", {})

        if not bellwethers:
            return "No bellwether scores calculated yet."

        sorted_b = sorted(bellwethers.items(), key=lambda x: x[1], reverse=True)

        lines = [
            f"## Top {top_n} Bellwether Streamers",
            "Bellwethers are cultural hubs whose audience vibes and behaviors are highly correlated with the rest of the ecosystem.",  # noqa: E501
            "",
        ]

        for idx, (h, s) in enumerate(sorted_b[:top_n]):
            t_label = "None"
            for t_id, t_info in vibe_tribes.items():
                if h in t_info.get("members", []):
                    t_label = t_info.get("label")
                    break
            lines.append(
                f"{idx + 1}. **{h}** (Centrality: {s:.4f}) - *Tribe: {t_label}*"
            )

        return "\n".join(lines)
    except Exception as e:
        return f"Error retrieving bellwether rankings: {e}"
