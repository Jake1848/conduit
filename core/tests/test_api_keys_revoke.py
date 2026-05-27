"""API key list + revocation."""

import pytest


@pytest.mark.asyncio
async def test_revoke_blocks_subsequent_auth(client):
    # Mint a write key.
    r = await client.post("/v1/api-keys", json={"scope": "write", "label": "temp"})
    assert r.status_code == 201
    secret = r.json()["secret"]
    key_id = r.json()["id"]

    # The new key works.
    r = await client.get(
        "/v1/agents", headers={"Authorization": f"Bearer {secret}"}
    )
    assert r.status_code == 200

    # Revoke it via admin (bootstrap key).
    r = await client.delete(f"/v1/api-keys/{key_id}")
    assert r.status_code == 204, r.text

    # Now any auth with that secret returns 401.
    r = await client.get(
        "/v1/agents", headers={"Authorization": f"Bearer {secret}"}
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_revoke_is_idempotent(client):
    r = await client.post("/v1/api-keys", json={"scope": "read", "label": "again"})
    key_id = r.json()["id"]

    r1 = await client.delete(f"/v1/api-keys/{key_id}")
    assert r1.status_code == 204
    r2 = await client.delete(f"/v1/api-keys/{key_id}")
    assert r2.status_code == 204


@pytest.mark.asyncio
async def test_revoke_unknown_returns_404(client):
    r = await client.delete("/v1/api-keys/key_does_not_exist")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_keys_omits_secret(client):
    await client.post("/v1/api-keys", json={"scope": "write", "label": "one"})
    await client.post("/v1/api-keys", json={"scope": "read", "label": "two"})

    r = await client.get("/v1/api-keys")
    assert r.status_code == 200, r.text
    items = r.json()["data"]
    assert len(items) >= 3  # the two we created + the bootstrap

    for item in items:
        # No raw key bytes leak through the list endpoint.
        assert "secret" not in item
        assert "key_hash" not in item
        assert {"id", "label", "scope", "prefix", "created_at", "revoked"} <= set(item.keys())


@pytest.mark.asyncio
async def test_list_keys_requires_admin(client):
    r = await client.post("/v1/api-keys", json={"scope": "read", "label": "readonly"})
    read_only = r.json()["secret"]
    r = await client.get(
        "/v1/api-keys", headers={"Authorization": f"Bearer {read_only}"}
    )
    assert r.status_code == 403
