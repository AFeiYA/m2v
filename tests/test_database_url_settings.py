"""Connection URL normalization never requires real database credentials."""
import pytest
from sqlalchemy.engine import make_url
from src.settings import Settings


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
@pytest.mark.parametrize("password", ["test@password", "test%40password"])
def test_postgres_password_at_sign_is_encoded_once(scheme, password):
    settings = Settings(
        _env_file=None,
        DATABASE_URL=f"{scheme}://tester:{password}@db.example.invalid:5432/app",
        R2_ACCOUNT_ID="",
    )
    parsed = make_url(settings.DATABASE_URL)
    assert parsed.drivername == "postgresql+asyncpg"
    assert parsed.host == "db.example.invalid"
    assert parsed.password == "test@password"
    assert parsed.database == "app"
    assert "%2540" not in settings.DATABASE_URL


def test_sqlite_database_url_is_unchanged():
    url = "sqlite+aiosqlite:///./test.db"
    assert Settings(_env_file=None, DATABASE_URL=url, R2_ACCOUNT_ID="").DATABASE_URL == url
