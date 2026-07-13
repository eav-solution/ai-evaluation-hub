def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/db")
    monkeypatch.setenv("JWT_SECRET", "s3cret")
    from app.config import Settings

    s = Settings()
    assert s.database_url == "postgresql+psycopg://u:p@h:5432/db"
    assert s.jwt_secret == "s3cret"
    assert s.jwt_expire_minutes == 1440
