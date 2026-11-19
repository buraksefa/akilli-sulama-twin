"""Arayüzler birim testleri (Faz 3).

Kapsam:
- FastAPI REST API uç noktaları (/health, /parks, /parks/{id}/zones, /weather, /telemetry, /qc, /simulate, /compare, /sensitivity, /testbed/state, /testbed/advice)
- Bearer token kimlik doğrulama kontrolleri
- Typer CLI komutları (fetch-era5, qc, simulate, compare, sensitivity, export-figures)
"""

import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from twin.api.app import app, export_openapi_json, get_api_secret_token
from twin.cli import app as cli_app


class TestAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.test_token = "secure_test_token_2026"
        os.environ["API_AUTH_TOKEN"] = self.test_token
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {self.test_token}"}

    def test_health_public(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ok")

    def test_unauthorized_and_missing_token_access(self):
        # Yetkilendirme başlığı olmadan erişim engellenmeli
        res = self.client.get("/parks")
        self.assertEqual(res.status_code, 401)

        # Hatalı token ile erişim engellenmeli
        res_bad = self.client.get("/parks", headers={"Authorization": "Bearer wrong_token"})
        self.assertEqual(res_bad.status_code, 401)

    def test_missing_env_token_raises_runtime_error(self):
        old_token = os.environ.pop("API_AUTH_TOKEN", None)
        try:
            with self.assertRaises(RuntimeError):
                get_api_secret_token()
        finally:
            if old_token:
                os.environ["API_AUTH_TOKEN"] = old_token

    def test_parks_and_zones(self):
        res = self.client.get("/parks", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        parks = res.json()
        self.assertTrue(len(parks) >= 2)

        res_zones = self.client.get("/parks/yildiz/zones", headers=self.headers)
        self.assertEqual(res_zones.status_code, 200)
        self.assertTrue(len(res_zones.json()) >= 1)

    def test_weather_and_telemetry(self):
        res_w = self.client.get("/weather?park_id=yildiz&season=2024", headers=self.headers)
        self.assertEqual(res_w.status_code, 200)
        self.assertEqual(len(res_w.json()), 214)

        res_t = self.client.get("/telemetry?node=node01&limit=10", headers=self.headers)
        self.assertEqual(res_t.status_code, 200)
        self.assertEqual(len(res_t.json()), 10)
        self.assertEqual(res_t.json()[0]["source"], "synthetic")

    def test_simulate_and_compare(self):
        sim_payload = {"park_id": "yildiz", "season": 2024, "strategy": "S4"}
        res_s = self.client.post("/simulate", json=sim_payload, headers=self.headers)
        self.assertEqual(res_s.status_code, 200)
        self.assertIn("metrics", res_s.json())

        comp_payload = {"park_id": "yildiz", "season": 2024, "strategies": ["S0", "S1", "S4"]}
        res_c = self.client.post("/compare", json=comp_payload, headers=self.headers)
        self.assertEqual(res_c.status_code, 200)
        self.assertIn("critic_weights", res_c.json())

    def test_qc_and_sensitivity_endpoints(self):
        qc_payload = {
            "records": [
                {"time": "2024-05-01T00:00:00Z", "seq": 1, "soil_raw": 500, "temp_c": 22.0, "hum_pct": 50.0},
                {"time": "2024-05-01T00:01:00Z", "seq": 2, "soil_raw": 502, "temp_c": 22.1, "hum_pct": 50.2},
            ],
            "interval_s": 60.0,
        }
        res_qc = self.client.post("/qc", json=qc_payload, headers=self.headers)
        self.assertEqual(res_qc.status_code, 200)
        self.assertEqual(res_qc.json()["total_records"], 2)

        sens_payload = {"park_id": "yildiz", "season": 2024, "method": "oat"}
        res_sens = self.client.post("/sensitivity", json=sens_payload, headers=self.headers)
        self.assertEqual(res_sens.status_code, 200)
        self.assertIn("results", res_sens.json())

    def test_testbed_state_and_advice(self):
        res_state = self.client.get("/testbed/state", headers=self.headers)
        self.assertEqual(res_state.status_code, 200)
        self.assertEqual(res_state.json()["node"], "node01")
        self.assertEqual(res_state.json()["source"], "synthetic")

        res_adv = self.client.get("/testbed/advice", headers=self.headers)
        self.assertEqual(res_adv.status_code, 200)
        self.assertTrue(res_adv.json()["requires_approval"])
        self.assertEqual(res_adv.json()["source"], "synthetic")

    def test_openapi_export(self):
        with tempfile.TemporaryDirectory() as d:
            out_file = Path(d) / "openapi.json"
            p = export_openapi_json(out_file)
            self.assertTrue(p.exists())


class TestCLICommands(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def test_cli_fetch_era5(self):
        with tempfile.TemporaryDirectory() as d:
            out_path = Path(d) / "era5.csv"
            res = self.runner.invoke(
                cli_app,
                ["fetch-era5", "--start", "2024-05-01", "--end", "2024-05-03", "--out", str(out_path)],
            )
            self.assertEqual(res.exit_code, 0)
            self.assertTrue(out_path.exists())

    def test_cli_simulate_and_compare(self):
        with tempfile.TemporaryDirectory() as d:
            out_sim = Path(d) / "sim.csv"
            res = self.runner.invoke(
                cli_app,
                [
                    "simulate",
                    "--park",
                    "yildiz",
                    "--season",
                    "2024",
                    "--strategy",
                    "S4",
                    "--out",
                    str(out_sim),
                ],
            )
            self.assertEqual(res.exit_code, 0)
            self.assertTrue(out_sim.exists())

            out_comp = Path(d) / "comp.csv"
            res_comp = self.runner.invoke(
                cli_app, ["compare", "--park", "yildiz", "--season", "2024", "--out", str(out_comp)]
            )
            self.assertEqual(res_comp.exit_code, 0)
            self.assertTrue(out_comp.exists())


if __name__ == "__main__":
    unittest.main()
