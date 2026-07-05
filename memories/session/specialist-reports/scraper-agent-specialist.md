## Full Report

### Layer: scraper-agent-specialist

### Files Touched
- `src/ag_kaggle_5day/agents/gcp_storage.py`
- `src/ag_kaggle_5day/agents/advisor.py`

### Diff Summary
- `gcp_storage.py`:
  - Updated the `get_historical_sentiment_summary` function to explicitly map `"chat_volatility"` and `"rolling_sentiment_score"` fields from the Firestore snapshot document map into the returned history dictionaries.
- `advisor.py`:
  - Updated the `streamers_details` loop inside `_generate_comparison_report` to retrieve and format the platform along with the login string: `user_name (user_login:platform)`. It uses the `platform` key if present, falling back to `"youtube"` if the channel ID starts with `"UC"` or `"twitch"` otherwise.
  - Updated the system instructions prompt in `_generate_comparison_report` to tell the LLM to format YouTube streamer links using the format `<a href="https://youtube.com/channel/user_login" target="_blank">user_name</a>` and Twitch streamer links using the Twitch format.

### Commands Run
- `python -m py_compile src/ag_kaggle_5day/agents/advisor.py` → Exit 0 (Valid syntax)
- `poetry run pytest src/ag_kaggle_5day/agents/test_agents.py` → Exit 0 (86 passed)

### Decisions & Alternatives
- Exposing the fields inside the history dictionary projection avoids database restructuring.
- Supplying the platform suffix to the LLM provides it with explicit, unambiguous platform data so it can accurately distinguish and link to Twitch vs YouTube channel IDs.

### Risks / Follow-ups
- None.
