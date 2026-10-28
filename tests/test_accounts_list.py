from tests.helpers import make_account


def test_list_accounts_paginates_newest_first(client):
    empty = client.get("/accounts")
    assert empty.status_code == 200
    assert empty.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}

    ids = [make_account(client, f"Holder {i}") for i in range(5)]

    first = client.get("/accounts").json()
    assert first["total"] == 5
    assert (first["limit"], first["offset"]) == (20, 0)
    assert [a["id"] for a in first["items"]] == list(reversed(ids))
    assert all(a["balance"] == "0.00" for a in first["items"])

    pages = [
        client.get("/accounts", params={"limit": 2, "offset": offset}).json()
        for offset in (0, 2, 4)
    ]
    assert [len(page["items"]) for page in pages] == [2, 2, 1]
    assert [page["total"] for page in pages] == [5, 5, 5]
    assert [a["id"] for page in pages for a in page["items"]] == list(reversed(ids))

    past_end = client.get("/accounts", params={"offset": 10}).json()
    assert past_end["items"] == [] and past_end["total"] == 5


def test_list_accounts_rejects_invalid_pagination(client):
    for query in ("limit=0", "limit=101", "limit=abc", "offset=-1"):
        r = client.get(f"/accounts?{query}")
        assert r.status_code == 422, query
        assert r.json()["error"]["code"] == "INVALID_PAGINATION", query
