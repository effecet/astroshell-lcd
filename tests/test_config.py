import pytest

from astroshell.config import AppConfig, apply_overrides, load_config


def test_unset_flags_keep_the_config_file_values(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("display:\n  refresh_interval: 1.0\n  layout: mining\n  theme: matrix\n")
    cfg = apply_overrides(load_config(str(cfg_file)))
    assert cfg.display.refresh_interval == 1.0
    assert cfg.display.layout == "mining"
    assert cfg.display.theme == "matrix"


def test_flags_override_the_config_file():
    cfg = apply_overrides(AppConfig(), layout="gaming", theme="dark_green", refresh_interval=0.5)
    assert (cfg.display.layout, cfg.display.theme, cfg.display.refresh_interval) == (
        "gaming",
        "dark_green",
        0.5,
    )


def test_shipped_config_keeps_the_2s_refresh():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    assert load_config(str(root / "config.yaml")).display.refresh_interval == 2.0


def test_yaml_number_as_string_is_coerced(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text('display:\n  refresh_interval: "1.5"\n')
    assert apply_overrides(load_config(str(cfg_file))).display.refresh_interval == 1.5


@pytest.mark.parametrize("bad", ["0", "-1", "null", "fast"])
def test_bad_refresh_interval_is_rejected(tmp_path, bad):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(f"display:\n  refresh_interval: {bad}\n")
    with pytest.raises(ValueError, match="refresh_interval"):
        apply_overrides(load_config(str(cfg_file)))


def test_bad_interval_flag_is_rejected():
    with pytest.raises(ValueError, match="greater than 0"):
        apply_overrides(AppConfig(), refresh_interval=0)
