from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def isolate_gcp_services(request):
    """
    Globally mocks Firestore and BigQuery clients to return None in test runs,
    preventing any accidental reads or writes to the production databases.
    Bypasses mocking specifically for tests in tests/test_gcp_integration.py.
    """
    # Do not isolate integration tests that verify real GCP connectivity
    if "test_gcp_integration" in request.node.fspath.strpath:
        yield
        return

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=None,
        ),
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_bigquery_client",
            return_value=None,
        ),
    ):
        yield
