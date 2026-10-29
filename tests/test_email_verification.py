from unittest.mock import AsyncMock, MagicMock
import asyncio

import pytest
from fastapi import HTTPException

from src import auth


def test_unverified_password_user_cannot_create_or_access_account(monkeypatch):
    monkeypatch.setattr(auth, 'decode_token', lambda token: {
        'type': 'access', 'provider': 'firebase', 'sub': 'user',
        'sign_in_provider': 'password', 'email_verified': False,
    })
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.get_user_from_token('token', db))
    assert exc.value.status_code == 403
    assert exc.value.detail == 'EMAIL_VERIFICATION_REQUIRED'
    db.execute.assert_not_awaited()


@pytest.mark.parametrize('provider', ['password', 'google.com'])
def test_verified_firebase_user_can_access_existing_account(monkeypatch, provider):
    monkeypatch.setattr(auth, 'decode_token', lambda token: {
        'type': 'access', 'provider': 'firebase', 'sub': 'user',
        'sign_in_provider': provider, 'email_verified': True,
    })
    user = MagicMock(is_active=True, display_name='Artist')
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    db.execute.return_value = result
    assert asyncio.run(auth.get_user_from_token('token', db)) is user
    assert user.is_verified is True
