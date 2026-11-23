"""Sensör düğümü platformu: sözleşme, simülatör, alım, QC, uyarılar ve komut yayını yasağı."""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from twin.devices.ingest import Ingestor
from twin.devices.registry import load_registry, registry_from_world
from twin.devices.schema import Telemetry, parse_topic, raw_to_vwc, topic_for, vwc_to_raw
from twin.devices.service import backfill, load_world, make_simulator
from twin.devices.simulator import daylight_fraction, diurnal_temp
from twin.devices.store import TelemetryStore

TZ = ZoneInfo("Europe/Istanbul")
FIRMWARE_SAMPLE = (
    '{"node":"yildiz-01","seq":12,"up":3600,"ts":1795400000,"soil_raw":640,"soil_pct":60.0,'
    '"soil_vwc":0.240,"temp_c":21.5,"hum_pct":55.0,"pump_s":0.0,"rssi":-67,"err":0}'
)


def _weather(today: pd.Timestamp, past=40, future=7, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(today - pd.Timedelta(days=past), periods=past + future, freq="D")
    w = pd.DataFrame(
        {
            "eto_mm": rng.uniform(2, 5, len(idx)),
            "rain_mm": np.where(rng.random(len(idx)) < 0.2, rng.gamma(1.5, 6, len(idx)), 0.0),
            "rain_prob_pct": 50.0,
            "temp_max": 22.0,
            "temp_min": 12.0,
        },
        index=idx,
    )
    w["is_forecast"] = w.index >= today
    w.attrs["source"] = "synthetic"
    return w


@pytest.fixture(scope="module")
def world():
    return load_world()


@pytest.fixture()
def devices(world):
    return registry_from_world(world)


# ------------------------------------------------------------------ sözleşme
def test_firmware_payload_is_valid_telemetry():
    t = Telemetry.model_validate(json.loads(FIRMWARE_SAMPLE))
    assert t.node == "yildiz-01" and t.soil_vwc == 0.24 and t.sim is False


def test_topics_never_cmd():
    assert topic_for("TN-1", "telemetry") == "sulama/TN-1/telemetry"
    for bad in ("cmd", "ack"):
        with pytest.raises(ValueError):
            topic_for("TN-1", bad)
    with pytest.raises(ValueError):
        topic_for("a/b", "telemetry")
    assert parse_topic("sulama/TN-1/status") == ("TN-1", "status")


def test_no_cmd_publish_in_devices_package():
    """Paket hiçbir yerde cmd konusuna yayın yapmaz; yayınlar topic_for üzerinden geçer."""
    src = "\n".join(p.read_text() for p in Path("src/twin/devices").glob("*.py"))
    assert "/cmd" not in src.replace("`cmd`", "")
    for line in re.findall(r".*\.publish\(.*", src):
        assert "topic_for(" in line


def test_acl_sim_and_ingest_users_cannot_write_cmd():
    acl = Path("server/mosquitto/config/acl").read_text()
    blocks = {b.split()[1]: b for b in re.split(r"\n(?=user )", acl) if b.startswith("user ")}
    for user in ("devsim", "ingest"):
        assert user in blocks
        assert "cmd" not in blocks[user]


def test_raw_vwc_roundtrip():
    for v in (0.05, 0.2, 0.35):
        assert abs(raw_to_vwc(vwc_to_raw(v)) - v) < 0.001


def test_registry_file_matches_world(world):
    reg = load_registry()
    assert {d.node for d in reg} == {s.sensor.sensor_id for s in world.sensors}
    assert all(d.source in ("simulated", "real") for d in reg)


# ------------------------------------------------------------------ simülatör
def test_daylight_and_temperature_curves():
    assert daylight_fraction(3) == 0 and daylight_fraction(22) == 1
    xs = [daylight_fraction(h) for h in np.arange(0, 24, 0.5)]
    assert all(b >= a for a, b in zip(xs, xs[1:]))
    assert abs(diurnal_temp(6, 10, 20) - 10) < 1e-9 and abs(diurnal_temp(15, 10, 20) - 20) < 1e-9


def test_simulator_readings_valid(world, devices):
    today = pd.Timestamp("2026-07-10")
    sim = make_simulator(world, devices, weather_provider=lambda: _weather(today))
    msgs = sim.readings(datetime(2026, 7, 10, 12, 0, tzinfo=TZ))
    missing = {n for n, s in sim._nodes.items() if s.day_missing}
    assert {m.node for m in msgs} == set(sim.simulated_nodes) - missing
    for m in msgs:
        assert m.sim and 0.0 <= m.soil_vwc <= 0.6 and m.temp_c is not None
        Telemetry.model_validate_json(m.model_dump_json(by_alias=True))


def test_soil_dries_during_day_without_water(world, devices):
    today = pd.Timestamp("2026-07-10")
    w = _weather(today)
    w.loc[today, ["rain_mm", "eto_mm"]] = [0.0, 6.0]
    sim = make_simulator(world, devices, weather_provider=lambda: w)
    sim.prepare(today)
    sim._dose_z[:] = 0.0
    cell = world.sensors[0].cell
    assert sim.cell_theta(cell, 7.0) > sim.cell_theta(cell, 18.0)


def test_real_devices_are_not_simulated(world, devices):
    devices[0].source = "real"
    sim = make_simulator(world, devices, weather_provider=lambda: _weather(pd.Timestamp("2026-07-10")))
    assert devices[0].node not in sim.simulated_nodes


# ------------------------------------------------------------------ alım
def _ingestor(tmp_path, devices):
    return Ingestor(TelemetryStore(str(tmp_path / "t.sqlite")), devices)


def test_ingest_store_duplicate_and_unknown(tmp_path, devices):
    ing = _ingestor(tmp_path, devices)
    node = devices[0].node
    msg = Telemetry(node=node, seq=1, ts=1795400000, soil_raw=640, soil_vwc=0.24, rssi=-60, battery_v=4.1)
    payload = msg.model_dump_json(by_alias=True).encode()
    assert ing.handle(f"sulama/{node}/telemetry", payload) == "stored"
    assert ing.handle(f"sulama/{node}/telemetry", payload) == "duplicate"
    assert ing.handle(f"sulama/{node}/telemetry", b"{bozuk") == "rejected"
    assert ing.handle(
        "sulama/yabanci-1/telemetry", FIRMWARE_SAMPLE.replace("yildiz-01", "yabanci-1").encode()
    )
    kinds = set(ing.store.alerts(active_only=True)["kind"])
    assert {"bad_payload", "unknown_device"} <= kinds
    assert ing.handle("sulama/x/cmd", b"PUMP") == "ignored"


def test_ingest_range_and_device_error(tmp_path, devices):
    ing = _ingestor(tmp_path, devices)
    node = devices[0].node
    bad = Telemetry(node=node, seq=1, ts=1795400000, soil_vwc=0.9)
    err = Telemetry(node=node, seq=2, ts=1795400900, soil_vwc=0.2, err=2)
    ing.handle(f"sulama/{node}/telemetry", bad.model_dump_json(by_alias=True).encode())
    ing.handle(f"sulama/{node}/telemetry", err.model_dump_json(by_alias=True).encode())
    assert list(ing.store.readings(node)["live_qc"]) == ["range", "device_error"]
    assert "device_error" in set(ing.store.alerts(active_only=True)["kind"])


def test_rssi_alert_hysteresis(tmp_path, devices):
    ing = _ingestor(tmp_path, devices)
    node = devices[0].node
    for i, rssi in enumerate([-90, -84, -81]):  # -84 eşik üstü ama kapanma payı (+3) altında
        m = Telemetry(node=node, seq=i + 1, ts=1795400000 + 900 * i, soil_vwc=0.2, rssi=rssi)
        ing.handle(f"sulama/{node}/telemetry", m.model_dump_json(by_alias=True).encode())
        active = set(ing.store.alerts(active_only=True)["kind"])
        assert ("rssi_weak" in active) == (i < 2)


def test_status_and_offline(tmp_path, devices):
    ing = _ingestor(tmp_path, devices)
    node = devices[0].node
    ing.handle(f"sulama/{node}/status", b"offline", received=100)
    assert "offline" in set(ing.store.alerts(active_only=True)["kind"])
    ing.handle(f"sulama/{node}/status", b"online", received=200)
    assert ing.store.alerts(active_only=True).empty
    opened = ing.check_offline(now=10_000)
    assert set(opened) == {d.node for d in devices}  # hiç ölçüm yok


def test_backfill_daily_qc_and_restart(tmp_path, world, devices):
    today = pd.Timestamp("2026-07-10")
    sim = make_simulator(world, devices, weather_provider=lambda: _weather(today, past=45, future=7))
    store = TelemetryStore(str(tmp_path / "t.sqlite"))
    ing = Ingestor(store, devices)
    start = datetime(2026, 7, 8, 0, 0, tzinfo=TZ)
    n = backfill(sim, ing, start, start + timedelta(hours=36), 900)
    assert n > 0
    qd = store.qc_daily()
    assert set(qd["day"]) == {"2026-07-08"} and len(qd) >= len(devices) - 3
    # yeniden başlatma: QC durumu depodan kurulur
    ing2 = Ingestor(store, devices)
    node = qd["node"].iloc[0]
    assert len(ing2._qc[node].history) == len(ing._qc[node].history)


def test_container_and_deploy_never_ship_iski_or_secrets():
    """İmaj ve rsync İSKİ verisini, ham veriyi ve sırları dışarıda bırakır (CLAUDE.md §2.1–2.2)."""
    for f in (".containerignore", ".dockerignore"):
        txt = Path(f).read_text()
        for must in ("data/iski", "data/raw", ".env", "server/mosquitto/config/passwd", "*.sqlite*"):
            assert must in txt, (f, must)
    deploy = Path("server/podman/deploy.sh").read_text()
    for must in ("data/iski/", "data/raw/", ".env", "passwd", "config.h"):
        assert f"--exclude '{must}" in deploy or must in deploy
    cf = Path("server/podman/Containerfile").read_text()
    assert "COPY data/ " not in cf and "data/iski" not in cf.replace("data/iski ve", "")
    for unit in Path("server/podman").glob("*.container"):
        assert "cmd" not in unit.read_text().split("[Container]")[1]


def test_restart_restores_open_day_buffer(tmp_path, devices):
    ing = _ingestor(tmp_path, devices)
    node = devices[0].node
    for i in range(3):
        m = Telemetry(node=node, seq=i + 1, ts=1795400000 + 900 * i, soil_vwc=0.2 + 0.01 * i)
        ing.handle(f"sulama/{node}/telemetry", m.model_dump_json(by_alias=True).encode())
    ing2 = Ingestor(ing.store, devices)
    assert ing2._buf[node][1] == ing._buf[node][1]
