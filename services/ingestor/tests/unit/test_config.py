import pytest

from ingestor.config import ConfigurationError, load_settings


def test_defaults_are_spec_defaults_without_database_requirement():
    settings = load_settings({})
    assert settings.provider_timeout_seconds == 60
    assert settings.provider_max_decompressed_bytes == 100_000_000
    assert settings.refresh_stale_hours == 48
    assert settings.run_lease_seconds == 300
    assert settings.run_timeout_minutes == 45
    assert settings.heartbeat_seconds == 30
    assert len(settings.enabled_chains) == 8
    assert "shufersal" not in settings.enabled_chains
    assert "carrefour" not in settings.enabled_chains
    assert settings.log_provider == "console"
    assert settings.log_level == "info"


def test_database_configuration_never_appears_in_repr_or_validation_errors():
    url = "postgresql://worker:synthetic-secret@db.example.test/catalog"
    settings = load_settings({"DATABASE_URL": url}, require_database=True)
    assert settings.database_url == url
    assert "synthetic-secret" not in repr(settings)
    with pytest.raises(ConfigurationError) as error:
        load_settings({"DATABASE_URL": "invalid-synthetic-secret"}, require_database=True)
    assert "DATABASE_URL" in str(error.value)
    assert "synthetic-secret" not in str(error.value)


def test_missing_required_database_reports_only_setting_name():
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        load_settings({}, require_database=True)


@pytest.mark.parametrize(
    "name",
    [
        "PROVIDER_TIMEOUT_SECONDS",
        "PROVIDER_MAX_DECOMPRESSED_BYTES",
        "REFRESH_STALE_HOURS",
        "RUN_LEASE_SECONDS",
        "RUN_TIMEOUT_MINUTES",
        "HEARTBEAT_SECONDS",
    ],
)
@pytest.mark.parametrize("value", ["0", "-1", "NaN", "1.5", "", "synthetic-secret"])
def test_invalid_limits_are_rejected_without_echoing_values(name, value):
    with pytest.raises(ConfigurationError) as error:
        load_settings({name: value})
    assert name in str(error.value)
    assert "synthetic-secret" not in str(error.value)


def test_heartbeat_must_fit_inside_lease():
    with pytest.raises(ConfigurationError, match="HEARTBEAT_SECONDS"):
        load_settings({"RUN_LEASE_SECONDS": "30"})


@pytest.mark.parametrize(
    "name,value", [("RUN_LEASE_SECONDS", "301"), ("RUN_TIMEOUT_MINUTES", "46")]
)
def test_startup_rejects_limits_the_worker_cannot_honor(name, value):
    with pytest.raises(ConfigurationError, match=name):
        load_settings({name: value})


@pytest.mark.parametrize("value", ["", "unknown", "shufersal,shufersal"])
def test_enabled_chains_reject_empty_unknown_and_duplicate_ids(value):
    with pytest.raises(ConfigurationError, match="ENABLED_CHAINS"):
        load_settings({"ENABLED_CHAINS": value})


def test_chain_subset_and_version_fallback():
    settings = load_settings({"ENABLED_CHAINS": "shufersal,carrefour", "GITHUB_SHA": "commit"})
    assert settings.enabled_chains == ("shufersal", "carrefour")
    assert settings.app_version == "commit"
    assert (
        load_settings({"GITHUB_SHA": "commit", "APP_VERSION": "release"}).app_version == "release"
    )


@pytest.mark.parametrize("name", ["LOG_LEVEL", "LOG_PROVIDER"])
def test_unsupported_logging_settings_fail_explicitly(name):
    with pytest.raises(ConfigurationError, match=name):
        load_settings({name: "unsupported"})
