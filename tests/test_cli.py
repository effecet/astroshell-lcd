from typer.testing import CliRunner

from astroshell import daemon
from astroshell.main import cli


def test_run_without_flags_uses_config_yaml(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("display:\n  refresh_interval: 1.0\n  layout: mining\n")
    seen = {}
    monkeypatch.setattr(daemon, "run", lambda cfg: seen.setdefault("cfg", cfg))
    result = CliRunner().invoke(cli, ["run", "--config", str(cfg_file)])
    assert result.exit_code == 0, result.output
    assert seen["cfg"].display.refresh_interval == 1.0
    assert seen["cfg"].display.layout == "mining"


def test_sim_without_flags_uses_config_yaml(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("display:\n  refresh_interval: 1.0\n  layout: gaming\n")
    monkeypatch.chdir(tmp_path)
    seen = {}
    monkeypatch.setattr(daemon, "run", lambda cfg: seen.setdefault("cfg", cfg))
    result = CliRunner().invoke(cli, ["sim"])
    assert result.exit_code == 0, result.output
    assert seen["cfg"].display.layout == "gaming"
    assert seen["cfg"].display.refresh_interval == 1.0
    assert seen["cfg"].display.simulate is True


def test_sim_flags_override_config_yaml(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("display:\n  layout: gaming\n")
    monkeypatch.chdir(tmp_path)
    seen = {}
    monkeypatch.setattr(daemon, "run", lambda cfg: seen.setdefault("cfg", cfg))
    result = CliRunner().invoke(
        cli, ["sim", "--layout", "minimal", "--theme", "matrix", "--interval", "0.5"]
    )
    assert result.exit_code == 0, result.output
    assert seen["cfg"].display.layout == "minimal"
    assert seen["cfg"].display.theme == "matrix"
    assert seen["cfg"].display.refresh_interval == 0.5


def test_run_flags_override_config_yaml(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("display:\n  layout: mining\n")
    seen = {}
    monkeypatch.setattr(daemon, "run", lambda cfg: seen.update(cfg=cfg))
    result = CliRunner().invoke(
        cli, ["run", "--config", str(cfg_file), "--theme", "matrix", "--layout", "gaming", "--sim"]
    )
    assert result.exit_code == 0, result.output
    assert seen["cfg"].display.theme == "matrix"
    assert seen["cfg"].display.layout == "gaming"
    assert seen["cfg"].display.simulate is True
