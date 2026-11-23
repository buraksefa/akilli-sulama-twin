"""`twin devices …` komutları: kayıt, simülatör, alım, yerel test aracısı ve geriye dönük doldurma."""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import typer

from twin.devices.registry import REGISTRY_PATH, load_registry, registry_from_world, save_registry

app = typer.Typer(help="Sensör düğümü platformu (sanal ve gerçek düğümler)")
log = logging.getLogger("twin.devices")


@app.command("registry")
def registry_cmd(
    write: bool = typer.Option(False, "--write", help="Sanal dünyadan kaydı yeniden üret ve yaz"),
    path: Path = typer.Option(REGISTRY_PATH, "--path"),
):
    """Cihaz kaydını göster; --write ile sanal dünyadaki sensörlerden üret (gerçek düğüm satırları korunur)."""
    from twin.devices.service import load_world

    if write:
        new = registry_from_world(load_world())
        if path.exists():
            real = {d.node: d for d in load_registry(path) if d.source == "real"}
            new = [real.get(d.node, d) for d in new] + [
                d for n, d in real.items() if n not in {x.node for x in new}
            ]
        save_registry(
            new, path, note="Sanal Yıldız dünyasından üretildi (world_seed 7); gerçek düğümde source=real"
        )
    for d in load_registry(path):
        typer.echo(f"{d.node:16s} {d.source:9s} {d.zone:10s} {d.lat:.5f},{d.lon:.5f}  {d.name}")


@app.command("simulate")
def simulate_cmd(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(1883, "--port"),
    interval: Optional[int] = typer.Option(None, "--interval", help="Saniye; varsayılan config (900)"),
    anonymous: bool = typer.Option(
        False, "--anonymous", help="Yalnız yerel test aracısı için kimliksiz bağlan"
    ),
    once: bool = typer.Option(False, "--once", help="Tek tur yayınla ve çık"),
    seed: int = typer.Option(0, "--seed"),
):
    """Sanal düğümleri gerçek zamanda yayınla (sulama/<node>/telemetry ve /status; cmd yok)."""
    from twin.config import TwinConfig
    from twin.devices.mqtt import Publisher, credentials
    from twin.devices.service import TZ, load_world, make_simulator

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    step = int(interval or TwinConfig().devices.report_interval_s.value)
    sim = make_simulator(load_world(), seed=seed)
    pub = Publisher(host, port, credentials("MQTT_SIM", anonymous))
    for node in sim.simulated_nodes:
        pub.status(node, "online")
    try:
        while True:
            now = datetime.now(TZ)
            try:
                msgs = sim.readings(now)
            except (
                Exception
            ) as e:  # hava servisi vb. geçici hata: servis kapanmaz, sonraki turda yeniden dener
                log.error("Bu tur yayın yapılamadı: %s", e)
                if once:
                    raise
                time.sleep(max(60.0, step / 3))
                continue
            for m in msgs:
                pub.telemetry(m)
            log.info(
                "%d/%d düğüm yayınladı (hava: %s, gün %s)",
                len(msgs),
                len(sim.simulated_nodes),
                sim.weather_source,
                sim.day.date(),
            )
            if once:
                break
            time.sleep(max(1.0, step - (datetime.now(TZ) - now).total_seconds()))
    except KeyboardInterrupt:
        pass
    finally:
        for node in sim.simulated_nodes:
            pub.status(node, "offline")
        pub.close()


@app.command("ingest")
def ingest_cmd(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(1883, "--port"),
    db: Optional[str] = typer.Option(
        None, "--db", help="SQLite yolu; varsayılan TWIN_DEVICE_DB ya da data/devices"
    ),
    anonymous: bool = typer.Option(False, "--anonymous"),
):
    """Telemetri ve durum konularını dinle; depoya yaz, QC uygula, uyarı üret."""
    from twin.devices.ingest import Ingestor
    from twin.devices.mqtt import credentials, subscribe_forever
    from twin.devices.store import TelemetryStore

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = TelemetryStore(db)
    ing = Ingestor(store, load_registry())
    counts = {}

    def on_message(topic, payload):
        r = ing.handle(topic, payload)
        counts[r] = counts.get(r, 0) + 1

    def on_tick():
        newly = ing.check_offline()
        log.info("alım: %s; yeni çevrimdışı: %s", counts, newly or "-")

    log.info("Depo: %s", store.path)
    subscribe_forever(host, port, credentials("MQTT_INGEST", anonymous), on_message, on_tick=on_tick)


@app.command("broker")
def broker_cmd(port: int = typer.Option(1883, "--port")):
    """Yalnız yerel geliştirme için kimliksiz MQTT aracısı (amqtt, 127.0.0.1). Sunucuda Mosquitto kullanılır."""
    import asyncio

    from amqtt.broker import Broker

    cfg = {
        "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
        "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}},
    }

    async def main():
        b = Broker(cfg)
        await b.start()
        typer.echo(f"amqtt aracı 127.0.0.1:{port} (yalnız yerel test)")
        while True:
            await asyncio.sleep(3600)

    asyncio.run(main())


@app.command("backfill")
def backfill_cmd(
    hours: int = typer.Option(48, "--hours", help="Geriye kaç saat"),
    db: Optional[str] = typer.Option(None, "--db"),
    seed: int = typer.Option(0, "--seed"),
):
    """Son N saati aracısız simüle edip depoya yaz (panel demosu; tüm satırlar sim=1)."""
    from twin.config import TwinConfig
    from twin.devices.ingest import Ingestor
    from twin.devices.service import TZ, backfill, load_world, make_simulator
    from twin.devices.store import TelemetryStore

    step = int(TwinConfig().devices.report_interval_s.value)
    end = datetime.now(TZ).replace(second=0, microsecond=0)
    end -= timedelta(minutes=end.minute % (step // 60 or 1))
    store = TelemetryStore(db)
    devices = load_registry()
    n = backfill(
        make_simulator(load_world(), devices, seed=seed),
        Ingestor(store, devices),
        end - timedelta(hours=hours),
        end,
        step,
    )
    typer.echo(f"{n} ileti işlendi → {store.path}")
