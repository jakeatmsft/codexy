import json
import os
from unittest.mock import patch

import pytest

from codexy.config import load_config, normalize_foundry_endpoint


def config_at(tmp_path, **kwargs):
    return load_config(
        config_path=tmp_path / "config.json",
        instructions_path=tmp_path / "instructions.md",
        cwd=tmp_path,
        disable_project_doc=True,
        **kwargs,
    )


def test_env_is_loaded_at_runtime_without_mutating_process(tmp_path):
    (tmp_path / ".env").write_text(
        'CODEXY_AUTH_MODE=api-key\nOPENAI_API_KEY="local test key"\n'
        "CODEXY_MODEL=env-model\nOPENAI_TIMEOUT_MS=2500\nCODEXY_FULL_STDOUT=true\n"
    )
    (tmp_path / "config.json").write_text(json.dumps({"model": "stored-model"}))
    with patch.dict(os.environ, {}, clear=True):
        config = config_at(tmp_path)
        assert config["api_key"] == "local test key"
        assert config["model"] == "env-model"
        assert config["timeout"] == 2.5
        assert config["full_stdout"] is True
        assert "OPENAI_API_KEY" not in os.environ
        (tmp_path / ".env").write_text("CODEXY_MODEL=changed-model\n")
        assert config_at(tmp_path)["model"] == "changed-model"


def test_exported_values_and_explicit_flags_override_env(tmp_path):
    (tmp_path / ".env").write_text("CODEXY_MODEL=file-model\nCODEXY_FULL_STDOUT=true\n")
    with patch.dict(os.environ, {"CODEXY_MODEL": "exported-model"}, clear=True):
        config = config_at(tmp_path, full_stdout=False)
    assert config["model"] == "exported-model"
    assert config["full_stdout"] is False


def test_entra_is_default_and_does_not_require_api_key(tmp_path):
    with patch.dict(os.environ, {}, clear=True):
        config = config_at(tmp_path)
    assert config["auth_mode"] == "entra"
    assert config["api_key"] is None
    assert config["model"] == ""
    assert config["check_updates"] is False


def test_custom_env_file_and_azure_settings(tmp_path):
    (tmp_path / "custom.env").write_text(
        "AZURE_OPENAI_ENDPOINT=https://example.services.ai.azure.com/\n"
        "AZURE_OPENAI_DEPLOYMENT_NAME=deployment\nAZURE_TENANT_ID=tenant\n"
        "AZURE_CLI_COMMAND=/custom/bin/az\n"
    )
    with patch.dict(os.environ, {"CODEXY_ENV_FILE": "custom.env"}, clear=True):
        config = config_at(tmp_path)
    assert config["azure_tenant_id"] == "tenant"
    assert config["azure_cli_command"] == "/custom/bin/az"
    assert config["base_url"] == "https://example.services.ai.azure.com/openai/v1/"
    assert config["model"] == "deployment"


@pytest.mark.parametrize(
    "setting",
    [
        "CODEXY_AUTH_MODE=invalid",
        "OPENAI_TIMEOUT_MS=wrong",
        "OPENAI_TIMEOUT_MS=0",
        "OPENAI_TIMEOUT_MS=-1",
        "CODEXY_CHECK_UPDATES=wrong",
    ],
)
def test_invalid_env_fails_with_setting_name(tmp_path, setting):
    (tmp_path / ".env").write_text(setting)
    with patch.dict(os.environ, {}, clear=True), pytest.raises(ValueError, match=setting.split("=")[0]):
        config_at(tmp_path)


def test_yaml_default_config_is_actually_loaded(tmp_path):
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("model: from-yaml\n")
    with (
        patch.dict(os.environ, {"CODEXY_AUTH_MODE": "api-key"}, clear=True),
        patch("codexy.config.CONFIG_YAML_FILEPATH", yaml_path),
        patch("codexy.config.CONFIG_JSON_FILEPATH", tmp_path / "config.json"),
    ):
        config = load_config(cwd=tmp_path, instructions_path=tmp_path / "instructions.md", disable_project_doc=True)
    assert config["model"] == "from-yaml"
    assert not (tmp_path / "config.json").exists()


@pytest.mark.parametrize(
    "endpoint",
    ["https://example.openai.azure.com", "https://example.openai.azure.com/", "https://example.openai.azure.com/openai/v1/"],
)
def test_normalize_resource_and_v1_endpoint(endpoint):
    assert normalize_foundry_endpoint(endpoint) == "https://example.openai.azure.com/openai/v1/"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.test",
        "https://user:password@example.test",
        "https://example.test/api/projects/demo",
        "https://example.test/?token=secret",
    ],
)
def test_reject_invalid_foundry_endpoint(endpoint):
    with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
        normalize_foundry_endpoint(endpoint)


def test_entra_deployment_overrides_stored_public_model(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"model": "o4-mini"}))
    (tmp_path / ".env").write_text("AZURE_OPENAI_DEPLOYMENT_NAME=my-deployment\n")
    with patch.dict(os.environ, {}, clear=True):
        assert config_at(tmp_path)["model"] == "my-deployment"
