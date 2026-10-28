from tests.helpers import make_account, post_tx


def _seed_history(client):
    acc = make_account(client)
    post_tx(client, acc, "credit", "100.00", "R1")
    post_tx(client, acc, "debit", "10.00", "R2")
    post_tx(client, acc, "credit", "20.00", "R3")
    post_tx(client, acc, "debit", "5.00", "R4")
    return acc


def test_history_is_newest_first_and_filters_by_type(client):
    acc = _seed_history(client)

    body = client.get(f"/accounts/{acc}/transactions").json()
    assert body["total"] == 4
    assert [t["reference_id"] for t in body["items"]] == ["R4", "R3", "R2", "R1"]

    for type_, expected in (("credit", ["R3", "R1"]), ("debit", ["R4", "R2"])):
        filtered = client.get(f"/accounts/{acc}/transactions", params={"type": type_}).json()
        assert filtered["total"] == 2
        assert [t["reference_id"] for t in filtered["items"]] == expected
        assert all(t["type"] == type_ for t in filtered["items"])


def test_history_paginates(client):
    acc = _seed_history(client)

    page1 = client.get(
        f"/accounts/{acc}/transactions", params={"limit": 3, "offset": 0}
    ).json()
    page2 = client.get(
        f"/accounts/{acc}/transactions", params={"limit": 3, "offset": 3}
    ).json()

    assert [t["reference_id"] for t in page1["items"]] == ["R4", "R3", "R2"]
    assert [t["reference_id"] for t in page2["items"]] == ["R1"]
    assert page1["total"] == page2["total"] == 4
    assert (page1["limit"], page1["offset"]) == (3, 0)
    assert (page2["limit"], page2["offset"]) == (3, 3)


def test_history_is_scoped_to_its_account_and_starts_empty(client):
    a, b = make_account(client), make_account(client)

    empty = client.get(f"/accounts/{a}/transactions").json()
    assert empty["items"] == [] and empty["total"] == 0

    post_tx(client, a, "credit", "1.00", "A1")
    post_tx(client, b, "credit", "1.00", "B1")

    body = client.get(f"/accounts/{a}/transactions").json()
    assert body["total"] == 1
    assert [t["reference_id"] for t in body["items"]] == ["A1"]


def test_history_rejects_invalid_parameters(client):
    acc = make_account(client)
    cases = [
        ({"limit": 0}, "INVALID_PAGINATION"),
        ({"offset": -1}, "INVALID_PAGINATION"),
        ({"type": "bogus"}, "INVALID_TRANSACTION_TYPE"),
    ]
    for params, code in cases:
        r = client.get(f"/accounts/{acc}/transactions", params=params)
        assert r.status_code == 422, params
        assert r.json()["error"]["code"] == code, params
