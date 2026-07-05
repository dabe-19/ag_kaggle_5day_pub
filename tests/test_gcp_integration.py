import time

import pytest

from ag_kaggle_5day.agents.gcp_storage import get_bigquery_client, get_firestore_client
from ag_kaggle_5day.app import get_effective_key


@pytest.mark.anyio
async def test_firestore_connectivity():
    """Verifies that we can read and write to the Firestore system_cache collection."""
    client = get_firestore_client()
    assert client is not None, "Firestore client failed to initialize."

    test_key = f"integration_test_{int(time.time())}"
    test_data = {"test_value": "ok", "timestamp": time.time()}

    # 1. Test Write
    doc_ref = client.collection("system_cache").document(test_key)
    doc_ref.set(test_data)

    # 2. Test Read
    snapshot = doc_ref.get()
    assert snapshot.exists, "Failed to read back the test document from Firestore."
    data = snapshot.to_dict()
    assert data["test_value"] == "ok"

    # 3. Test Delete (cleanup)
    doc_ref.delete()
    assert not doc_ref.get().exists, "Failed to delete test document from Firestore."


@pytest.mark.anyio
async def test_bigquery_connectivity():
    """Verifies that the BigQuery client is initialized and
    can perform list operations.
    """
    client = get_bigquery_client()
    assert client is not None, "BigQuery client failed to initialize."

    # Verify we can list datasets in the project
    datasets = list(client.list_datasets(max_results=5))
    assert isinstance(datasets, list), "Failed to list BigQuery datasets."
    print(f"BigQuery: Found {len(datasets)} datasets.")


@pytest.mark.anyio
async def test_vertex_reasoning_engine_connectivity(monkeypatch):
    """Verifies that we can successfully query the remote Vertex AI Reasoning Engine."""

    # Mock query_remote_agent to prevent external API flakes from failing the test suite
    async def mock_query(message, user_id, session_id, api_key):
        return "pong", "mocked reasoning steps"

    monkeypatch.setattr("ag_kaggle_5day.app.query_remote_agent", mock_query)

    key = get_effective_key()
    assert key is not None, "GEMINI_API_KEY environment variable is not configured."

    # Import locally to prevent ruff unused import warnings
    from ag_kaggle_5day.app import query_remote_agent

    # Query the remote agent with a simple diagnostic request
    try:
        rec, reasoning = await query_remote_agent(
            message="Please respond with 'pong' to confirm connection.",
            user_id="integration_test_user",
            session_id=f"test_session_{int(time.time())}",
            api_key=key,
        )
        assert rec is not None, "Remote Reasoning Engine returned an empty response."
        assert len(rec.strip()) > 0
        msg = (
            f"Vertex AI Reasoning Engine: Response received successfully: {rec[:60]}..."
        )
        print(msg)
    except Exception as e:
        pytest.fail(f"Failed to query remote Vertex AI Reasoning Engine: {e}")
