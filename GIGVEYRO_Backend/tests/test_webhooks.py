from app.core.security import create_access_token
from app.enums.account import UserRole


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def test_merchant_creates_webhook(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["url"] == "https://example.com/hook"
    assert body["event_types"] == ["invoice.paid"]
    assert body["status"] == "active"
    assert len(body["secret"]) > 20
    assert "encrypted_secret" not in body


async def test_create_webhook_rejects_unknown_event_type(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["totally.made.up"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422


async def test_create_webhook_rejects_bad_url(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "ftp://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422


async def test_create_webhook_rejects_plain_http(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "http://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422


# ---- SSRF PROTECTION (H2 security fix) -----------------------------------


async def test_create_webhook_allows_public_url(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://public-webhook.test/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 201


async def test_create_webhook_rejects_loopback_ip(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://127.0.0.1/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422


async def test_create_webhook_rejects_localhost_literal(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://localhost/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422


async def test_create_webhook_rejects_class_a_private_ip(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://10.1.2.3/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422


async def test_create_webhook_rejects_class_b_private_ip(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://172.16.5.5/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422


async def test_create_webhook_rejects_class_c_private_ip(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://192.168.1.1/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422


async def test_create_webhook_rejects_link_local_metadata_ip(client, make_account):
    """169.254.169.254 - the AWS/GCP/Azure cloud metadata endpoint."""
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://169.254.169.254/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422


async def test_create_webhook_rejects_ipv6_loopback(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://[::1]/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422


async def test_create_webhook_rejects_ipv6_link_local(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://[fe80::1]/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422


async def test_create_webhook_rejects_ipv6_unique_local(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://[fd00::1]/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422


async def test_create_webhook_rejects_hostname_resolving_to_internal_service(
    client, make_account
):
    """internal-service.test resolves (per the test DNS fixture) to
    10.0.0.5 - a hostname that isn't obviously "internal" by string alone,
    exactly the case a naive localhost/127.0.0.1 string blocklist misses."""
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://internal-service.test/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422


async def test_create_webhook_rejects_hostname_resolving_to_cloud_metadata(
    client, make_account
):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://metadata.test/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422


async def test_create_webhook_rejects_hostname_with_one_private_address_among_many(
    client, make_account
):
    """mixed-address.test resolves to both a public and a private address -
    if even one resolved address is internal, the whole destination is
    unsafe regardless of which address a client happens to connect to."""
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://mixed-address.test/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422


async def test_update_webhook_rejects_url_change_to_private_address(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/webhooks",
        json={"url": "https://public-webhook.test/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )
    webhook_id = create.json()["id"]

    response = await client.patch(
        f"/merchant/webhooks/{webhook_id}",
        json={"url": "https://10.0.0.1/hook"},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422
    # the original safe URL must not have been overwritten
    get_response = await client.get(
        f"/merchant/webhooks/{webhook_id}", headers=_auth_headers(merchant)
    )
    assert get_response.json()["url"] == "https://public-webhook.test/hook"


async def test_update_webhook_allows_url_change_to_another_public_address(
    client, make_account
):
    merchant = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/webhooks",
        json={"url": "https://public-webhook.test/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )
    webhook_id = create.json()["id"]

    response = await client.patch(
        f"/merchant/webhooks/{webhook_id}",
        json={"url": "https://also-public-webhook.test/hook"},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 200
    assert response.json()["url"] == "https://also-public-webhook.test/hook"


async def test_user_cannot_create_webhook(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(user),
    )

    assert response.status_code == 403


async def test_webhook_list_never_returns_secret(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    response = await client.get("/merchant/webhooks", headers=_auth_headers(merchant))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert "secret" not in body["items"][0]
    assert "encrypted_secret" not in body["items"][0]


async def test_merchant_cannot_see_another_merchants_webhooks(client, make_account):
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant_a),
    )
    webhook_id = create.json()["id"]

    get_response = await client.get(
        f"/merchant/webhooks/{webhook_id}", headers=_auth_headers(merchant_b)
    )
    list_response = await client.get("/merchant/webhooks", headers=_auth_headers(merchant_b))

    assert get_response.status_code == 404
    assert list_response.json()["total"] == 0


async def test_merchant_disables_webhook(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )
    webhook_id = create.json()["id"]

    response = await client.patch(
        f"/merchant/webhooks/{webhook_id}",
        json={"status": "disabled"},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "disabled"


async def test_deliveries_list_scoped_to_own_webhook(client, make_account):
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant_a),
    )
    webhook_id = create.json()["id"]

    own = await client.get(
        f"/merchant/webhooks/{webhook_id}/deliveries", headers=_auth_headers(merchant_a)
    )
    other = await client.get(
        f"/merchant/webhooks/{webhook_id}/deliveries", headers=_auth_headers(merchant_b)
    )

    assert own.status_code == 200
    assert own.json()["total"] == 0
    assert other.status_code == 404
