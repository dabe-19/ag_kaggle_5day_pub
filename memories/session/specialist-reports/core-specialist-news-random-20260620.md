## Full Report

### Layer: core-specialist

### Files Touched
- `src/ag_kaggle_5day/app.py`
- `tests/test_main.py`

### Diff Summary
- Implemented `/api/news/random` API endpoint in `app.py` to return up to 5 articles. It fetches recent articles from Firestore's `news_articles` collection, falls back to parsing the local `news_cache.md` file, and falls back to a list of default hardcoded industry news if all other sources are unavailable.
- Added a unit test `test_api_news_random` in `tests/test_main.py` to verify the random news API response format and limit.

### Commands Run
- `poetry run pytest tests/test_main.py` -> 21 passed (including the new random news endpoint test).
- `poetry run start --port 8009` -> Successfully booted and bound to port 8009.

### Decisions & Alternatives
- Shuffled news articles on the server-side to provide a dynamic, refreshing rolling update on each load or retry.
- Implemented three tiers of fallbacks (Firestore -> local cache file -> hardcoded default articles) to guarantee that the endpoint never fails or returns empty results, ensuring the pleasant failure UI always has content.

### Risks / Follow-ups
- Requires the `frontend-specialist` to implement the sequential fetch logic to prevent scraping race conditions and render the pleasant failure UI calling this random news endpoint on dashboard report errors.
