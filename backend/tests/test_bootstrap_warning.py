from types import SimpleNamespace
import pytest
from app.config import Settings
from app.security import bootstrap

@pytest.mark.parametrize("configured,generated", [("custom-configured", False), ("", True)])
def test_public_password_warns_even_when_environment_changes(monkeypatch, caplog, configured, generated):
    default = Settings.model_fields["BOOTSTRAP_ADMIN_PASSWORD"].default
    monkeypatch.setattr(bootstrap, "verify_password", lambda password, hashed: password == default)
    with caplog.at_level("WARNING", logger="sentinel.auth"):
        bootstrap._warn_if_default_password_still_set(SimpleNamespace(username="officer", password_hash="public"), configured, generated)
    assert "still using the password shipped" in caplog.text
    assert "does not reset an existing account" in caplog.text

def test_custom_password_does_not_trigger_public_password_warning(monkeypatch, caplog):
    monkeypatch.setattr(bootstrap, "verify_password", lambda password, hashed: False)
    with caplog.at_level("WARNING", logger="sentinel.auth"):
        bootstrap._warn_if_default_password_still_set(SimpleNamespace(username="officer", password_hash="custom"), "custom", False)
    assert not caplog.records
