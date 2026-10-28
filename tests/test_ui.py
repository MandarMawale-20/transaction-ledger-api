"""The dashboard is three static files served by the same app."""

import pytest


def test_dashboard_is_served_without_external_dependencies(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Ledger" in r.text
    assert "/static/styles.css" in r.text
    assert "/static/app.js" in r.text
    assert "https://fonts." not in r.text and "cdn." not in r.text


@pytest.mark.parametrize("path", ["/static/styles.css", "/static/app.js"])
def test_dashboard_assets_are_served(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert len(r.content) > 500


def test_dashboard_is_not_part_of_the_api_schema(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/" not in paths
    assert not any(path.startswith("/static") for path in paths)
