import pytest

from astroshell.stats.collector import rapl_delta


def test_rapl_delta_plain_increase():
    assert rapl_delta(1_000, 5_000, 262_143_328_850) == 4_000


def test_rapl_delta_wraps_at_the_counter_range_not_2_32():
    max_range = 262_143_328_850  # a real max_energy_range_uj value
    assert rapl_delta(max_range - 100, 50, max_range) == 150


def test_rapl_delta_equal_readings_is_zero():
    assert rapl_delta(500, 500, 262_143_328_850) == 0


def test_rapl_delta_unknown_range_falls_back_to_2_32():
    assert rapl_delta(2**32 - 10, 5, 0) == 15


def _collector(monkeypatch, tmp_path, energy, range_text):
    import astroshell.stats.collector as col

    energy_file = tmp_path / "energy_uj"
    range_file = tmp_path / "max_energy_range_uj"
    if range_text is not None:
        range_file.write_text(range_text)
    monkeypatch.setattr(col, "RAPL_ENERGY_PATH", str(energy_file))
    monkeypatch.setattr(col, "RAPL_RANGE_PATH", str(range_file))
    c = col.StatsCollector.__new__(col.StatsCollector)
    c._rapl_range_uj = col.StatsCollector._read_rapl_range_uj()
    c._last_energy_uj = None
    c._last_energy_time = 0.0
    return c, energy_file


def test_range_is_read_from_sysfs(monkeypatch, tmp_path):
    c, _ = _collector(monkeypatch, tmp_path, None, "262143328850\n")
    assert c._rapl_range_uj == 262_143_328_850


@pytest.mark.parametrize("range_text", [None, "0", "garbage"])
def test_missing_or_bad_range_falls_back(monkeypatch, tmp_path, range_text):
    c, _ = _collector(monkeypatch, tmp_path, None, range_text)
    assert c._rapl_range_uj == 2**32


def test_failed_read_is_skipped_not_counted_as_a_wrap(monkeypatch, tmp_path):
    c, energy_file = _collector(monkeypatch, tmp_path, None, "262143328850")
    energy_file.write_text("1000000")
    assert c._read_cpu_power() == 0.0  # first good read only sets the baseline
    energy_file.unlink()
    assert c._read_cpu_power() == 0.0  # failed read: skipped
    assert c._last_energy_uj == 1_000_000  # baseline kept
    energy_file.write_text("3000000")
    watts = c._read_cpu_power()
    assert 0 < watts < 1e4  # 2 J over the elapsed time, not a 10^5 W spike
