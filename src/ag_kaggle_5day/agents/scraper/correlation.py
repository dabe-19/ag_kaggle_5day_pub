import logging
import time

logger = logging.getLogger("streamer_advisor.scraper")


def calculate_hourly_correlation(api_key: str = None) -> None:
    """Calculates hourly correlation matrices across all active streamers

    and logs them to BigQuery and Firestore.
    """
    import collections

    import numpy as np
    import pandas as pd

    from ag_kaggle_5day.agents.gcp_storage import (
        get_bigquery_client,
        get_firestore_client,
        store_correlation_history,
    )
    from ag_kaggle_5day.agents.scraper import (
        get_active_sentinel_channels,
        get_current_decayed_state,
    )

    logger.info("Computing hourly streamer correlation matrices...")
    fs = get_firestore_client()
    if not fs:
        logger.warning(
            "Firestore client not available. Skipping correlation computation."
        )
        return

    current_time = time.time()

    # 1. Fetch the active Sentinel cohort of 100 streamers
    try:
        streamers = get_active_sentinel_channels(fs)
    except Exception as e:
        logger.error(f"Correlation: Failed to get active sentinel channels: {e}")
        return

    if not streamers:
        logger.info("Correlation: No active streamers found. Skipping.")
        return

    # To keep dimensions stable and sorted consistently, sort alphabetically
    streamers = sorted(list(set(streamers)))

    # 2. Query BigQuery for the last 24 hours of sentiment_history
    bq = get_bigquery_client()
    history_data = []

    if bq:
        try:
            query = f"""
                SELECT
                  timestamp,
                  streamer_handle,
                  msg_per_minute,
                  chat_volatility,
                  rolling_sentiment_score,
                  viewer_count
                FROM `{bq.project}.streamer_metrics.sentiment_history`
                WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
                ORDER BY timestamp ASC
            """
            query_job = bq.query(query, timeout=30)
            results = query_job.result()
            for row in results:
                history_data.append(
                    {
                        "timestamp": row.timestamp.timestamp(),
                        "streamer_handle": row.streamer_handle.strip()
                        if row.streamer_handle.strip().lower().startswith("uc")
                        else row.streamer_handle.strip().lower(),
                        "msg_per_minute": row.msg_per_minute,
                        "chat_volatility": row.chat_volatility,
                        "rolling_sentiment_score": row.rolling_sentiment_score,
                        "viewer_count": row.viewer_count,
                        "interactive_density_rate": row.msg_per_minute
                        / row.viewer_count
                        if row.viewer_count and row.viewer_count > 0
                        else 0.0,
                    }
                )
            logger.info(
                "Correlation: Retrieved "
                f"{len(history_data)} historical rows from BigQuery."
            )
        except Exception as bq_err:
            logger.warning(
                f"Correlation: BigQuery query failed ({bq_err}). "
                "Running with fallback mock data."
            )

    # 3. Fallback / Mock Data Generation if BigQuery is unavailable
    if not history_data:
        now_ts = time.time()
        for h in streamers:
            ad_state = get_current_decayed_state(h, now_ts)
            base_vol = ad_state.get("chat_volatility", 0.3)
            base_mpm = ad_state.get("msg_per_minute", 10.0)
            base_sent = ad_state.get("rolling_sentiment_score", 0.1)
            base_view = ad_state.get("viewer_count", 500.0)

            for hour in range(24):
                ts = now_ts - (hour * 3600)
                v_count = max(1.0, base_view + float(np.random.normal(0, 50)))
                m_rate = max(0.0, base_mpm + float(np.random.normal(0, 2)))
                history_data.append(
                    {
                        "timestamp": ts,
                        "streamer_handle": h,
                        "msg_per_minute": m_rate,
                        "chat_volatility": max(
                            0.0, min(1.0, base_vol + float(np.random.normal(0, 0.05)))
                        ),
                        "rolling_sentiment_score": max(
                            -1.0, min(1.0, base_sent + float(np.random.normal(0, 0.1)))
                        ),
                        "viewer_count": v_count,
                        "interactive_density_rate": m_rate / v_count,
                    }
                )

    # 4. Build aligned Dense DataFrames
    df_all = pd.DataFrame(history_data)
    df_all["hour_bin"] = (df_all["timestamp"] // 3600).astype(int)

    metrics = [
        "chat_volatility",
        "rolling_sentiment_score",
        "msg_per_minute",
        "viewer_count",
        "interactive_density_rate",
    ]
    correlation_results = {}

    # Calculate active hours for schedule Jaccard overlap
    active_hours = collections.defaultdict(set)
    for row in history_data:
        h = row.get("streamer_handle")
        if h:
            v_count = row.get("viewer_count")
            m_rate = row.get("msg_per_minute")
            if (v_count is not None and v_count > 0) or (
                m_rate is not None and m_rate > 0
            ):  # noqa: E501
                hour_bin = int(row["timestamp"] // 3600)
                active_hours[h].add(hour_bin)

    # Precalculate schedule overlap fractions
    n = len(streamers)
    overlap_matrix = np.ones((n, n))
    for i, s_a in enumerate(streamers):
        for j, s_b in enumerate(streamers):
            if i != j:
                hours_a = active_hours.get(s_a, set())
                hours_b = active_hours.get(s_b, set())
                if not hours_a or not hours_b:
                    overlap_matrix[i, j] = 0.0
                else:
                    overlap_matrix[i, j] = len(hours_a.intersection(hours_b)) / len(
                        hours_a.union(hours_b)
                    )  # noqa: E501

    for metric in metrics:
        try:
            df_pivot = df_all.pivot_table(
                index="hour_bin",
                columns="streamer_handle",
                values=metric,
                aggfunc="mean",
            )
            df_pivot = df_pivot.reindex(columns=streamers).fillna(0.0)
            corr_df = df_pivot.corr()
            corr_df = corr_df.fillna(0.0)

            # Apply schedule overlap dampening to de-bias micro-streamers
            dampened_data = {}
            for i, s_a in enumerate(streamers):
                row_vals = corr_df.loc[s_a].tolist()
                dampened_row = []
                for j, val in enumerate(row_vals):
                    dampened_row.append(val * overlap_matrix[i, j])
                dampened_data[s_a] = dampened_row

            correlation_results[metric] = dampened_data
        except Exception as e:
            logger.error(f"Correlation: Failed to compute matrix for '{metric}': {e}")
            correlation_results[metric] = {s: [0.0] * len(streamers) for s in streamers}

    # 5. Compute Eigenvector Centrality (Bellwether Scores)
    bellwether_scores = {}
    try:
        n = len(streamers)
        adj_matrix = np.zeros((n, n))
        for i, s_a in enumerate(streamers):
            for j, s_b in enumerate(streamers):
                if s_a == s_b:
                    adj_matrix[i, j] = 1.0
                else:
                    cur_vals = [
                        correlation_results["chat_volatility"][s_a][j],
                        correlation_results["rolling_sentiment_score"][s_a][j],
                        correlation_results["msg_per_minute"][s_a][j],
                        correlation_results["viewer_count"][s_a][j],
                        correlation_results["interactive_density_rate"][s_a][j],
                    ]
                    avg_corr = sum(cur_vals) / len(cur_vals)
                    adj_matrix[i, j] = avg_corr if abs(avg_corr) > 0.2 else 0.0

        eigenvalues, eigenvectors = np.linalg.eig(adj_matrix)
        max_idx = np.argmax(np.real(eigenvalues))
        dom_vector = np.abs(np.real(eigenvectors[:, max_idx]))
        max_val = np.max(dom_vector)
        if max_val > 0:
            norm_vector = dom_vector / max_val
        else:
            norm_vector = np.zeros_like(dom_vector)
        bellwether_scores = {s: float(norm_vector[k]) for k, s in enumerate(streamers)}
    except Exception as eig_err:
        logger.error(
            f"Correlation: Failed to calculate eigenvector centrality: {eig_err}"
        )
        bellwether_scores = {s: 0.0 for s in streamers}

    # 6. Compute Convergence Velocity (1st Derivative)
    pair_velocities = {}
    pair_accelerations = {}
    try:
        if bq:
            query = f"""
                SELECT
                  timestamp,
                  streamer_a,
                  streamer_b,
                  volatility_cov,
                  sentiment_cov,
                  msg_rate_cov,
                  viewer_count_cov
                FROM `{bq.project}.streamer_metrics.correlation_history`
                WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
                ORDER BY timestamp ASC
            """
            query_job = bq.query(query, timeout=30)
            rows = query_job.result()

            pair_history = collections.defaultdict(list)
            for row in rows:
                sa_stripped = row.streamer_a.strip()
                sb_stripped = row.streamer_b.strip()
                sa = (
                    sa_stripped
                    if (sa_stripped.lower().startswith("uc") and len(sa_stripped) == 24)
                    else sa_stripped.lower()
                )
                sb = (
                    sb_stripped
                    if (sb_stripped.lower().startswith("uc") and len(sb_stripped) == 24)
                    else sb_stripped.lower()
                )
                key = (sa, sb) if sa < sb else (sb, sa)

                vals = []
                for m in [
                    "volatility_cov",
                    "sentiment_cov",
                    "msg_rate_cov",
                    "viewer_count_cov",
                ]:
                    v = getattr(row, m, None)
                    if v is not None:
                        vals.append(float(v))
                if vals:
                    score = sum(vals) / len(vals)
                    pair_history[key].append((row.timestamp.timestamp(), score))

            # Append current correlation score
            for i, s_a in enumerate(streamers):
                for j, s_b in enumerate(streamers):
                    if i > j:
                        key = (s_a, s_b) if s_a < s_b else (s_b, s_a)
                        cur_vals = [
                            correlation_results["chat_volatility"][s_a][j],
                            correlation_results["rolling_sentiment_score"][s_a][j],
                            correlation_results["msg_per_minute"][s_a][j],
                            correlation_results["viewer_count"][s_a][j],
                        ]
                        cur_score = sum(cur_vals) / len(cur_vals)
                        pair_history[key].append((current_time, cur_score))

            alpha = 0.3
            beta = 0.3
            for key, history in pair_history.items():
                if key[0] == key[1]:
                    continue
                history.sort(key=lambda x: x[0])
                if len(history) >= 2:
                    ema_v = 0.0
                    ema_a = 0.0
                    prev_t, prev_score = history[0]
                    prev_v = 0.0

                    for idx in range(1, len(history)):
                        curr_t, curr_score = history[idx]
                        dt = (curr_t - prev_t) / 3600.0
                        if dt <= 0.0:
                            dt = 0.001
                        raw_v = (curr_score - prev_score) / dt
                        ema_v = alpha * raw_v + (1.0 - alpha) * ema_v

                        raw_a = (ema_v - prev_v) / dt
                        ema_a = beta * raw_a + (1.0 - beta) * ema_a

                        prev_t, prev_score = curr_t, curr_score
                        prev_v = ema_v

                    pair_velocities[key] = float(ema_v)
                    pair_accelerations[key] = float(ema_a)
                else:
                    pair_velocities[key] = 0.0
                    pair_accelerations[key] = 0.0
    except Exception as bq_err:
        logger.warning(
            f"Correlation: Failed to calculate convergence velocity from BQ: {bq_err}"
        )

    # Fallback to zero if BQ is empty or failed
    for i, s_a in enumerate(streamers):
        for j, s_b in enumerate(streamers):
            if i > j:
                key = (s_a, s_b) if s_a < s_b else (s_b, s_a)
                if key not in pair_velocities:
                    pair_velocities[key] = 0.0
                if key not in pair_accelerations:
                    pair_accelerations[key] = 0.0

    # Format top 20 convergence velocities
    sorted_pairs = []
    for (s_a, s_b), vel in pair_velocities.items():
        if s_a == s_b:
            continue
        acc = pair_accelerations.get((s_a, s_b), 0.0)
        direction = "converging" if vel >= 0 else "diverging"
        sorted_pairs.append(
            {
                "streamer_a": s_a,
                "streamer_b": s_b,
                "velocity": abs(vel),
                "acceleration": acc,
                "direction": direction,
            }
        )
    sorted_pairs.sort(key=lambda x: x["velocity"], reverse=True)
    top_300_velocities = sorted_pairs[:300]

    # 7. Save latest matrix and hourly metrics to Firestore
    try:
        import json

        cov_doc = {
            "timestamp": current_time,
            "streamers": streamers,
            "correlation_matrices_json": json.dumps(correlation_results),
            "bellwether_scores": bellwether_scores,
            "convergence_velocity": top_300_velocities,
        }
        # Read old document to preserve daily cluster keys on hourly writes
        doc_ref = fs.collection("streamer_correlation").document("current")
        doc_existing = doc_ref.get()
        if doc_existing.exists:
            existing_data = doc_existing.to_dict()
            # Keep vibe_tribes, constellation_coords, inter_tribe_links,
            # and tribe_alignment_scores
            for k in [
                "vibe_tribes",
                "constellation_coords",
                "inter_tribe_links",
                "tribe_alignment_scores",
            ]:
                if k in existing_data:
                    cov_doc[k] = existing_data[k]

        doc_ref.set(cov_doc)
        logger.info(
            "Correlation: Successfully updated Firestore streamer_correlation/current."
        )
    except Exception as fs_err:
        logger.error(f"Correlation: Failed to save to Firestore: {fs_err}")

    # 8. Stream pairwise records to BigQuery
    pairwise_records = []
    for i, s_a in enumerate(streamers):
        for j, s_b in enumerate(streamers):
            if i >= j:
                key = (s_a, s_b) if s_a < s_b else (s_b, s_a)
                pairwise_records.append(
                    {
                        "streamer_a": s_a,
                        "streamer_b": s_b,
                        "volatility_cov": correlation_results["chat_volatility"][s_a][
                            j
                        ],
                        "sentiment_cov": correlation_results["rolling_sentiment_score"][
                            s_a
                        ][j],
                        "msg_rate_cov": correlation_results["msg_per_minute"][s_a][j],
                        "viewer_count_cov": correlation_results["viewer_count"][s_a][j],
                        "convergence_velocity": pair_velocities.get(key, 0.0),
                    }
                )

    try:
        store_correlation_history(pairwise_records)
    except Exception as bq_err:
        logger.error(f"Correlation: Failed to log history to BigQuery: {bq_err}")


def calculate_daily_ecosystem_analytics(api_key: str = None) -> None:
    """Computes Vibe Tribes (Spectral Clustering) and PCA Constellation coordinates

    across the active streamer cohort daily, logging snapshots to BigQuery.
    """
    import numpy as np
    from sklearn.cluster import SpectralClustering
    from sklearn.decomposition import PCA

    from ag_kaggle_5day.agents.gcp_storage import (
        get_firestore_client,
        store_ecosystem_snapshot,
    )
    from ag_kaggle_5day.agents.scraper import parse_json_response, safe_generate_content

    logger.info("Computing daily ecosystem analytics & cluster mapping...")
    fs = get_firestore_client()
    if not fs:
        return

    doc = fs.collection("streamer_correlation").document("current").get()
    if not doc.exists:
        logger.warning(
            "Daily Analytics: No hourly correlation document found. Skipping."
        )
        return

    import json

    data = doc.to_dict()
    streamers = data.get("streamers", [])
    correlation_matrices = {}
    if data.get("correlation_matrices_json"):
        try:
            correlation_matrices = json.loads(data["correlation_matrices_json"])
        except Exception as json_err:
            logger.error(f"Failed to parse correlation_matrices_json: {json_err}")
    if not correlation_matrices:
        correlation_matrices = data.get("correlation_matrices", {})
    bellwether_scores = data.get("bellwether_scores", {})

    if not streamers or not correlation_matrices:
        return

    # 1. Build combined correlation matrix
    metrics = [
        "chat_volatility",
        "rolling_sentiment_score",
        "msg_per_minute",
        "viewer_count",
        "interactive_density_rate",
    ]
    combined = np.zeros((len(streamers), len(streamers)))
    for metric in metrics:
        m_dict = correlation_matrices.get(metric, {})
        m_arr = np.zeros((len(streamers), len(streamers)))
        for i, s_a in enumerate(streamers):
            row = m_dict.get(s_a, [])
            for j in range(len(streamers)):
                m_arr[i, j] = row[j] if j < len(row) else 0.0
        combined += m_arr
    combined /= len(metrics)

    # 2. Run Spectral Clustering (transform correlation range [-1, 1] to positive
    # affinity [0, 1])
    affinity = (combined + 1.0) / 2.0

    n_clusters = min(5, len(streamers))
    if len(streamers) > 2:
        try:
            from sklearn.metrics import silhouette_score

            distance = 1.0 - affinity
            np.fill_diagonal(distance, 0.0)

            best_n = min(5, len(streamers))
            best_score = -1.0
            for k in range(2, min(9, len(streamers))):
                sc = SpectralClustering(
                    n_clusters=k, affinity="precomputed", random_state=42
                )
                labels = sc.fit_predict(affinity)
                if len(set(labels)) > 1:
                    score = silhouette_score(distance, labels, metric="precomputed")
                    if score > best_score:
                        best_score = score
                        best_n = k
            n_clusters = best_n
        except Exception as e:
            fallback_val = min(5, len(streamers))
            logger.warning(
                f"Daily Analytics: Failed to optimize cluster count: {e}. Defaulting to {fallback_val}."  # noqa: E501
            )
            n_clusters = fallback_val
    else:
        n_clusters = len(streamers)

    sc = SpectralClustering(
        n_clusters=n_clusters, affinity="precomputed", random_state=42
    )
    labels = sc.fit_predict(affinity)

    new_clusters = {}
    for i, s in enumerate(streamers):
        c_id = int(labels[i])
        if c_id not in new_clusters:
            new_clusters[c_id] = []
        new_clusters[c_id].append(s)

    # 3. Resolve Tribe Names (LLM-cached Option C)
    cache_doc = fs.collection("streamer_correlation").document("tribe_names").get()
    cached_tribes = {}
    if cache_doc.exists:
        cached_tribes = cache_doc.to_dict()

    tribe_names = {}
    used_cached_ids = set()
    colors = [
        "#22d3ee",
        "#ec4899",
        "#a855f7",
        "#10b981",
        "#f59e0b",
        "#3b82f6",
        "#ef4444",
        "#84cc16",
    ]

    for c_id, members in new_clusters.items():
        best_match_id = None
        best_jaccard = 0.0

        for cached_id, cached_info in cached_tribes.items():
            if cached_id in used_cached_ids:
                continue
            cached_members = cached_info.get("members", [])
            if not cached_members:
                continue
            intersection = len(set(members) & set(cached_members))
            union = len(set(members) | set(cached_members))
            jaccard = intersection / union if union > 0 else 0.0
            if jaccard > best_jaccard:
                best_jaccard = jaccard
                best_match_id = cached_id

        if best_jaccard >= 0.7 and best_match_id is not None:
            label = cached_tribes[best_match_id]["label"]
            description = cached_tribes[best_match_id].get(
                "description",
                "A dynamic faction of streamers bound by similar chat rhythms.",
            )
            used_cached_ids.add(best_match_id)
            logger.info(
                f"Daily Analytics: Reusing cached name '{label}' for cluster {c_id}"
            )
        else:
            archetypes = []
            games = []
            active_times = []

            for m in members[:5]:
                profile = fs.collection("streamer_profiles").document(m).get()
                if profile.exists:
                    p_data = profile.to_dict()
                    archetypes.append(
                        p_data.get("archetype_cluster", "Cozy_Social_Interactive")
                    )
                    games.append(p_data.get("primary_game", "Variety"))
                    active_times.append(p_data.get("time_active_cluster", "evening"))

            dominant_archetype = (
                max(set(archetypes), key=archetypes.count)
                if archetypes
                else "Cozy_Social_Interactive"
            )
            dominant_game = max(set(games), key=games.count) if games else "Variety"
            dominant_time = (
                max(set(active_times), key=active_times.count)
                if active_times
                else "evening"
            )

            prompt = f"""
            You are the Marquee Maker. Generate a creative, catchy,
            retro-neon arcade styled 2-to-3 word name and descriptive
            explanation for a group of live streamers whose properties are:
            - Dominant Streamer Archetype: {dominant_archetype}
            - Primary Game / Directory: {dominant_game}
            - Most Active Time Slot: {dominant_time}
            - Member handles: {", ".join(members[:8])}

            The name should sound like an '80s arcade cabinet marquee,
            a sci-fi faction, or a synthwave music syndicate.
            Examples: "Midnight Variety Syndicate", "Neon Sweat Lodge",
            "Chill Pixel Orbit", "Cozy Lagoon", "Vibe-Coupled Coalition".

            Return output in JSON format with exactly two keys:
            - 'name': a string representing the creative name.
            - 'description': a detailed 1-to-2 sentence description
              explaining the reasoning behind the name and how it reflects
              the shared characteristics and synergy of the members.

            Do NOT wrap output in markdown code fences. Return only raw valid JSON.
            """
            label = f"Tribe {c_id}"
            description = "A dynamic faction of streamers bound by similar chat rhythms and viewer flows."  # noqa: E501
            try:
                res = safe_generate_content(
                    api_key=api_key,
                    model=None,
                    contents=prompt,
                    chain_name="default",
                )
                try:
                    # Try to parse the response as JSON
                    json_data = parse_json_response(res.text.strip())
                    if (
                        isinstance(json_data, dict)
                        and "name" in json_data
                        and "description" in json_data
                    ):
                        label = (
                            json_data["name"].strip().replace('"', "").replace("'", "")
                        )
                        description = json_data["description"].strip()
                    else:
                        label = res.text.strip().replace('"', "").replace("'", "")
                except Exception:
                    label = res.text.strip().replace('"', "").replace("'", "")
            except Exception as llm_err:
                logger.error(
                    f"Daily Analytics: Failed to generate tribe name using LLM: {llm_err}"  # noqa: E501
                )

            logger.info(
                f"Daily Analytics: Generated new tribe name '{label}' with description: '{description}'"  # noqa: E501
            )

        tribe_names[str(c_id)] = {
            "label": label,
            "description": description,
            "members": members,
            "color": colors[c_id % len(colors)],
        }

    # Write tribe name cache
    fs.collection("streamer_correlation").document("tribe_names").set(tribe_names)

    # 4. Compute PCA Constellation Coordinates
    # Galaxy View Centroids
    centroids = []
    cluster_ids = sorted(list(new_clusters.keys()))
    for c_id in cluster_ids:
        members = new_clusters[c_id]
        member_indices = [streamers.index(m) for m in members]
        centroid = combined[member_indices, :].mean(axis=0)
        centroids.append(centroid)

    centroids = np.array(centroids)
    n_comp_galaxy = (
        min(3, len(centroids), centroids.shape[1]) if len(centroids) > 0 else 0
    )
    if n_comp_galaxy > 0:
        pca_galaxy = PCA(n_components=n_comp_galaxy)
        galaxy_coords_projected = pca_galaxy.fit_transform(centroids)
        if galaxy_coords_projected.shape[1] < 3:
            padding = np.zeros(
                (galaxy_coords_projected.shape[0], 3 - galaxy_coords_projected.shape[1])
            )
            galaxy_coords_projected = np.hstack((galaxy_coords_projected, padding))
    else:
        galaxy_coords_projected = np.zeros((len(centroids), 3))

    for d in range(3):
        min_val = galaxy_coords_projected[:, d].min()
        max_val = galaxy_coords_projected[:, d].max()
        if max_val - min_val > 1e-5:
            galaxy_coords_projected[:, d] = (
                2.0 * (galaxy_coords_projected[:, d] - min_val) / (max_val - min_val)
                - 1.0
            )
        else:
            n_points = galaxy_coords_projected.shape[0]
            if n_points > 1:
                galaxy_coords_projected[:, d] = np.linspace(-1.0, 1.0, n_points)
            else:
                galaxy_coords_projected[:, d] = 0.0

    galaxy_coords = {
        str(c_id): {
            "x": float(galaxy_coords_projected[i, 0]),
            "y": float(galaxy_coords_projected[i, 1]),
            "z": float(galaxy_coords_projected[i, 2]),
        }
        for i, c_id in enumerate(cluster_ids)
    }

    # Cluster View Members
    cluster_coords = {}
    for c_id, members in new_clusters.items():
        member_indices = [streamers.index(m) for m in members]
        sub_matrix = combined[member_indices][:, member_indices]

        if len(members) >= 3:
            n_comp_cluster = min(3, len(members), sub_matrix.shape[1])
            if n_comp_cluster > 0:
                pca_cluster = PCA(n_components=n_comp_cluster)
                projected = pca_cluster.fit_transform(sub_matrix)
                if projected.shape[1] < 3:
                    padding = np.zeros((projected.shape[0], 3 - projected.shape[1]))
                    projected = np.hstack((projected, padding))
            else:
                projected = np.zeros((len(members), 3))

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
            coords_dict = {
                m: {
                    "x": float(projected[k, 0]),
                    "y": float(projected[k, 1]),
                    "z": float(projected[k, 2]),
                }
                for k, m in enumerate(members)
            }
        else:
            coords_dict = {}
            for k, m in enumerate(members):
                angle = k * (2.0 * np.pi / len(members))
                coords_dict[m] = {
                    "x": float(np.cos(angle)),
                    "y": float(np.sin(angle)),
                    "z": 0.0,
                }
        cluster_coords[str(c_id)] = coords_dict

    # 4b. Compute Tribe Alignment Scores for Standard Members
    tribe_alignment_scores = {}
    for c_id, members in new_clusters.items():
        member_indices = [streamers.index(m) for m in members]
        for m in members:
            m_idx = streamers.index(m)
            other_indices = [idx for idx in member_indices if idx != m_idx]
            if other_indices:
                align_val = float(np.mean(combined[m_idx, other_indices]))
            else:
                align_val = 1.0
            tribe_alignment_scores[m] = max(-1.0, min(1.0, align_val))

    # 5. Compute Inter-Tribe Links
    inter_tribe_links = []
    for i, c_a in enumerate(cluster_ids):
        for j, c_b in enumerate(cluster_ids):
            if i > j:
                members_a = new_clusters[c_a]
                members_b = new_clusters[c_b]
                indices_a = [streamers.index(m) for m in members_a]
                indices_b = [streamers.index(m) for m in members_b]
                sub_matrix = combined[indices_a][:, indices_b]
                strength = float(np.mean(sub_matrix))
                inter_tribe_links.append(
                    {"from": str(c_a), "to": str(c_b), "strength": strength}
                )

    # 6. Save daily coords to Firestore streamer_correlation/current
    try:
        doc_ref = fs.collection("streamer_correlation").document("current")
        doc_existing = doc_ref.get()
        if doc_existing.exists:
            doc_data = doc_existing.to_dict()
        else:
            doc_data = {}

        doc_data["vibe_tribes"] = tribe_names
        doc_data["constellation_coords"] = {
            "galaxy": galaxy_coords,
            "clusters": cluster_coords,
        }
        doc_data["inter_tribe_links"] = inter_tribe_links
        doc_data["tribe_alignment_scores"] = tribe_alignment_scores

        doc_ref.set(doc_data, merge=True)
        logger.info("Daily Analytics: Saved coordinates and tribes successfully.")
    except Exception as fs_err:
        logger.error(f"Daily Analytics: Failed to merge into Firestore: {fs_err}")

    # 6b. Sync coordinates and tribes to all cohort members' streamer_profiles documents
    from ag_kaggle_5day.agents.scraper.feature_library import normalize_language_code

    for c_id, members in new_clusters.items():
        for m in members:
            # Get coordinate for member m
            m_coords = cluster_coords.get(str(c_id), {}).get(
                m, {"x": 0.0, "y": 0.0, "z": 0.0}
            )
            try:
                m_doc = fs.collection("streamer_profiles").document(m.lower()).get()
                m_data = m_doc.to_dict() if m_doc.exists else {}
                lang_norm = normalize_language_code(m_data.get("language") or "en")
                align_val = tribe_alignment_scores.get(m, 1.0)

                fs.collection("streamer_profiles").document(m.lower()).set(
                    {
                        "current_vibe_tribe": str(c_id),
                        "starfield_coordinates": m_coords,
                        "language": lang_norm,
                        "tribe_alignment": align_val,
                        "is_tribe_island": bool(align_val < 0.25),
                    },
                    merge=True,
                )
            except Exception as e:
                logger.warning(
                    f"Daily Analytics: Failed to sync coords to profile for {m}: {e}"
                )

    # 6c. Fetch and project coordinates for all custom
    # micro-streamers/bootstrapped profiles
    try:
        # Build active bellwethers list
        bellwethers = []
        for t_id, t_info in tribe_names.items():
            members = new_clusters.get(t_id, [])
            # Find top bellwether
            top_member = None
            top_score = -1.0
            for m in members:
                score = bellwether_scores.get(m, 0.0)
                if score > top_score:
                    top_score = score
                    top_member = m
            if top_member:
                bellwethers.append(top_member)
        if not bellwethers:
            bellwethers = ["shroud", "xqcow", "valkyrae", "asmongold", "pokimane"]

        profiles_ref = (
            fs.collection("streamer_profiles")
            .where("tier", "in", ["micro_streamer", "bootstrapped"])
            .stream()
        )
        for doc_p in profiles_ref:
            p_data = doc_p.to_dict()
            handle = doc_p.id.strip().lower()

            # Find closest bellwether
            best_well = bellwethers[0]
            best_score = -1.0
            for well in bellwethers:
                well_doc = (
                    fs.collection("streamer_profiles").document(well.lower()).get()
                )
                if well_doc.exists:
                    w_profile = well_doc.to_dict()
                    try:
                        from ag_kaggle_5day.agents.advisor import (
                            calculate_similarity_nvar,
                        )

                        sim, _, _ = calculate_similarity_nvar(p_data, w_profile)
                    except Exception:
                        sim = 0.0
                else:
                    sim = 0.0
                if sim > best_score:
                    best_score = sim
                    best_well = well

            # Find tribe
            assigned_tribe = "0"
            for t_id_cand, members_cand in new_clusters.items():
                if best_well in members_cand:
                    assigned_tribe = str(t_id_cand)
                    break

            # Project coords
            import random

            well_coords = cluster_coords.get(assigned_tribe, {}).get(best_well)
            if well_coords:
                coords_p = {
                    "x": well_coords.get("x", 0.0) + random.uniform(-0.15, 0.15),
                    "y": well_coords.get("y", 0.0) + random.uniform(-0.15, 0.15),
                    "z": well_coords.get("z", 0.0) + random.uniform(-0.15, 0.15),
                }
            else:
                coords_p = {
                    "x": random.uniform(-0.5, 0.5),
                    "y": random.uniform(-0.5, 0.5),
                    "z": random.uniform(-0.5, 0.5),
                }

            # Normalize language for micro-streamer
            lang_norm = normalize_language_code(p_data.get("language") or "en")

            # Write to Firestore
            fs.collection("streamer_profiles").document(handle).set(
                {
                    "starfield_coordinates": coords_p,
                    "current_vibe_tribe": assigned_tribe,
                    "language": lang_norm,
                },
                merge=True,
            )
    except Exception as e:
        logger.warning(
            f"Daily Analytics: Failed to project custom micro-streamers: {e}"
        )

    # 7. Write BQ Ecosystem Snapshot
    snapshot = {
        "num_tribes": len(tribe_names),
        "tribe_assignments": {s: int(labels[i]) for i, s in enumerate(streamers)},
        "tribe_labels": {
            str(c_id): info["label"] for c_id, info in tribe_names.items()
        },
        "bellwether_rankings": bellwether_scores,
        "constellation_coords_galaxy": galaxy_coords,
    }
    try:
        store_ecosystem_snapshot(snapshot)
    except Exception as e:
        logger.error(f"Daily Analytics: Failed to log snapshot to BQ: {e}")
