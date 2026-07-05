## Full Report

### Layer: scraper-agent-specialist

### Files Touched
- `src/ag_kaggle_5day/agents/scraper.py`
- `src/ag_kaggle_5day/agents/gcp_storage.py`
- `src/ag_kaggle_5day/agents/advisor.py`
- `src/ag_kaggle_5day/agents/test_agents.py`

### Diff Summary
- `scraper.py`: Renamed `calculate_hourly_covariance` to `calculate_hourly_correlation`. Implemented hourly calculation of Eigenvector Centrality (Bellwether scores) and Convergence Velocity (1st derivative based on BigQuery history). Implemented daily ecosystem calculations `calculate_daily_ecosystem_analytics` performing Spectral Clustering with LLM Jaccard-cached tribe naming, PCA coordinate projection for Galaxy and Cluster views, and BigQuery ecosystem snapshot logging.
- `gcp_storage.py`: Renamed `store_covariance_history` to `store_correlation_history` with the new schema (adding `convergence_velocity` column). Implemented `store_ecosystem_snapshot` writing to `streamer_metrics.ecosystem_snapshots` partitioned by timestamp with a 90-day retention.
- `advisor.py`: Renamed `get_streamer_correlations` (now reads from `streamer_correlation/current` Firestore doc) and extended the response payload to return tribe membership, bellwether score, and convergence velocities. Enriched `get_streamer_comprehensive_dossier` with sections for Vibe Tribe membership, Bellwether influence rank, and active convergence signals. Implemented the new tool functions `get_ecosystem_overview`, `get_tribe_details`, and `get_bellwether_rankings`.
- `test_agents.py`: Appended `test_ecosystem_starmap_tools` verifying all three new tool functions against mocked Firestore documents.

### Commands Run
- `poetry run pytest src/ag_kaggle_5day/agents/test_agents.py` (86 passed, 8 warnings in 33.72s)

### Decisions & Alternatives
- Transformed Pearson correlations from `[-1.0, 1.0]` to `[0.0, 1.0]` range using `(r + 1) / 2` for SpectralClustering to meet non-negative affinity requirements.
- Standardized PCA projection coordinates to `[-1.0, 1.0]` for Galaxy view and Cluster view, falling back to a deterministic circle layout for clusters with fewer than 3 members.
- Configured LLM tribe naming (Option C) using Jaccard similarity comparison (threshold of 0.7) against cached names to ensure stable visual identities on the Star Map.

### Risks / Follow-ups
- Follow up by implementing the frontend `starmap` tab (two-level semantic zoom, starfield warp transition, in-page contextual terminal command bar chat, card/drawer badges) in the `frontend-specialist` phase.
- Audit agent instructions, tool registries, and workflows in the `core-specialist` phase (since `advisor_agent` files live outside `src/ag_kaggle_5day/agents/`).
