from decimal import Decimal

from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.fees import FeeType
from app.repositories.fees import FeeRepository
from app.services.fees import FeePolicyService, FeeTerms


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _activate_policy(db_session, owner) -> None:
    fees = FeeRepository(db_session)
    terms = {fee_type: FeeTerms(False, 0, Decimal("0")) for fee_type in FeeType}
    draft = await FeePolicyService(fees).create(owner, terms)
    await FeePolicyService(fees).activate(owner, draft.id)


async def test_merchant_sees_own_fee_component(client, make_account, db_session):
    owner = await make_account(role=UserRole.OWNER)
    await _activate_policy(db_session, owner)
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.get("/merchant/fees", headers=_auth_headers(merchant))

    assert response.status_code == 200
    body = response.json()
    assert body["fee_type"] == "merchant_fee"
    assert body["enabled"] is False
    assert body["supported_for_charging"] is False


async def test_user_cannot_read_merchant_fee(client, make_account, db_session):
    owner = await make_account(role=UserRole.OWNER)
    await _activate_policy(db_session, owner)
    user = await make_account(role=UserRole.USER)

    response = await client.get("/merchant/fees", headers=_auth_headers(user))

    assert response.status_code == 403
