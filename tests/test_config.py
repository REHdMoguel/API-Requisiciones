import importlib
import json
import os


def test_default_settings_are_non_production(monkeypatch):
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    import config
    importlib.reload(config)
    assert config.settings.APP_ENV == "development"
    assert config.settings.DB_PASSWORD == ""
    assert config.settings.API_KEY == ""


def test_branch_config_from_json(monkeypatch):
    monkeypatch.setenv("DB_BRANCHES_JSON", json.dumps({"demo": {"host": "db", "path": "/x.fdb", "user": "u", "password": "p"}}))
    import multi_db
    importlib.reload(multi_db)
    assert multi_db.get_sucursal_config("demo")["host"] == "db"
