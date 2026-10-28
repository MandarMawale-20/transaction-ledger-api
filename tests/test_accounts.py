import uuid

from tests.helpers import make_account


def test_create_account_starts_at_zero(client):
    r = client.post("/accounts", json={"name": "Asha"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Asha"
    assert body["balance"] == "0.00"
    assert uuid.UUID(body["id"])
    assert body["created_at"]


def test_balance_endpoint_and_missing_account(client):
    acc = make_account(client)
    r = client.get(f"/accounts/{acc}/balance")
    assert r.status_code == 200
    assert r.json() == {"account_id": acc, "balance": "0.00"}

    missing = uuid.uuid4()
    r = client.get(f"/accounts/{missing}/balance")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


def test_invalid_account_input_is_rejected(client):
    payloads = [
        {},  # name is required
        {"name": ""},
        {"name": "   "},
        {"name": "Asha", "balance": 1000},  # server-owned fields
        {"name": "Asha", "id": str(uuid.uuid4())},
        {"name": "Asha", "created_at": "2020-01-01T00:00:00Z"},
    ]
    for payload in payloads:
        r = client.post("/accounts", json=payload)
        assert r.status_code == 422, payload
        assert r.json()["error"]["code"] == "VALIDATION_ERROR", payload

    assert client.get("/accounts").json()["total"] == 0


def test_framework_errors_use_the_documented_envelope(client):
    responses = [
        # Malformed JSON body.
        client.post("/accounts", content="{not json", headers={"Content-Type": "application/json"}),
        # Path parameter that is not a UUID.
        client.get("/accounts/not-a-uuid/balance"),
        # Unknown route.
        client.get("/nope"),
    ]
    assert [r.status_code for r in responses] == [422, 422, 404]
    assert [r.json()["error"]["code"] for r in responses] == [
        "VALIDATION_ERROR",
        "VALIDATION_ERROR",
        "NOT_FOUND",
    ]
    for response in responses:
        assert set(response.json()["error"]) == {"code", "message", "details"}
