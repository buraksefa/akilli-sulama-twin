"""Günlük sensör okumaları için çevrimiçi (gün gün) kalite kontrolü.

`qc/rules.py` saatlik saha CSV'leri için toplu (geriye dönük) bayrak üretir. Karar anında ise ikiz yalnız o güne
kadarki okumaları görür; bu sınıf her yeni okumayı geçmiş penceresine göre kabul ya da reddeder.

Kurallar (eşikler `TwinConfig.sensor_qc`, kaynak ve durum etiketli):

1. **Fiziksel aralık** (rules.py, VWC 0,0–0,60): aralık dışı okuma reddedilir.
2. **Kesinti** (SIMPaCT, > 3 gün): art arda okuma gelmeyen gün sayısı eşiği aşarsa sensör "kesintide".
   Yeni okuma geldiğinde sensör kendiliğinden geri döner.
3. **Eksik oranı** (SIMPaCT, > %50): son `missing_window_days` günde okumaların yarısından fazlası yoksa reddedilir.
4. **Donmuş değer** (SIMPaCT 120 saat, değişim < %1): son `frozen_window_days` (7) günlük okumanın
   (maks − min) / ortalama oranı %1'in altındaysa reddedilir. Saatlik veride 120 örnek varken günlükte 5 örnek
   gürültüyle rastlantısal olarak dar düşebildiği için pencere 7 güne uzatıldı (varsayım). Okumalar yeniden değişmeye başlayınca sensör geri döner.
5. **Tarla kapasitesi üstü** (fiziksel tutarlılık, varsayım): okuma nominal θFC + pay değerini art arda
   `above_fc_days` gün aşarsa sensör kalıcı olarak dışlanır. Toprak günlerce tarla kapasitesinin üstünde
   kalamaz; bu kural ıslak yöne kayan sensörü yakalamayı amaçlar. Kuru yöne kaymayı yakalayamaz.
6. **Doygunluk sonrası referans** (varsayım): dünkü net su girdisi ikizin kestirdiği açığı `saturation_buffer_mm`
   kadar aştıysa kök bölgesi tarla kapasitesinde olmalıdır. O sabah okuma nominal θFC + `saturation_margin`
   (0,09: θFC yayılımı + 3σ gürültü) üstündeyse sensör
   tek günde kalıcı dışlanır. Kurak hücredeki kayan sensör, 5. kuralda yalnız çok büyük sapmada yakalanır;
   bu kural yağıştan sonraki ilk sabahı kalibrasyon anı olarak kullanır.

7. **Model-sensör tutarlılığı / kayma** (varsayım): ikiz, sensörü hiç görmeyen bir açık döngü su dengesi modelini
   (uygulanan dozlar ve gözlenen hava ile) yan yana yürütür. Okuma − model θ farkının son `drift_window_days`
   gündeki EKK eğimi |eğim| > `drift_slope_max` ise sensör kalıcı dışlanır. Zon içi farklılık sabit ya da sınırlı
   bir fark üretir; kayma ise doğrusal büyür. Test iki yönlüdür (kuru yöne kaymayı da hedefler).

SIMPaCT'in sıçrama kuralı saatlik veri içindir. Günlük okumada yağış ve sulama gerçek sıçramalar ürettiği için
burada kullanılmadı.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional, Tuple

import numpy as np

from twin.config import SensorQCParameters

QC_REASONS = {
    "ok": "geçti",
    "nodata": "okuma yok",
    "range": "fiziksel aralık dışı",
    "gap": "3 günden uzun kesinti",
    "missing": "eksik oranı > %50",
    "frozen": "donmuş değer (7 gün, < %1 değişim)",
    "above_fc": "tarla kapasitesi üstü (kalıcı dışlandı)",
    "saturation_check": "doygunluk sonrası okuma tarla kapasitesinin üstünde (kalıcı dışlandı)",
    "drift": "model-sensör farkında eğilim / kayma (kalıcı dışlandı)",
}


@dataclass
class OnlineSensorQC:
    """Tek bir sensörün gün gün kalite kontrolü. `update` her gün bir kez çağrılır."""

    theta_fc_nominal: float
    params: SensorQCParameters = field(default_factory=SensorQCParameters)
    history: Deque[float] = field(default_factory=deque)
    gap_days: int = 0
    above_fc_run: int = 0
    excluded: bool = False
    exclusion_reason: str = ""
    last_reason: str = "ok"
    day: int = 0
    residuals: Deque[Tuple[int, float]] = field(default_factory=deque)
    drift_slope: float = float("nan")

    def __post_init__(self):
        n = max(int(self.params.missing_window_days.value), int(self.params.frozen_window_days.value))
        self.history = deque(maxlen=n)
        self.residuals = deque()

    def update(
        self, reading: float, saturated: bool = False, theta_model: Optional[float] = None
    ) -> Tuple[Optional[float], str]:
        """Okumayı geçmişe ekler; (kabul edilen değer ya da None, neden kodu) döndürür.

        `saturated`: ikize göre kök bölgesi dün yeterince su aldı ve bu sabah tarla kapasitesinde olmalı.
        `theta_model`: sensörü görmeyen açık döngü modelinin bu sabahki θ kestirimi (kayma testi; None ise atlanır).
        """
        p = self.params
        value = float(reading) if reading is not None else float("nan")
        self._update_drift(value, theta_model)
        self.day += 1
        if np.isfinite(value) and not (p.vwc_min.value <= value <= p.vwc_max.value):
            self.history.append(float("nan"))
            self.gap_days += 1
            return self._result(None, "range")
        self.history.append(value)
        self.gap_days = 0 if np.isfinite(value) else self.gap_days + 1

        if self.excluded:
            return self._result(None, self.exclusion_reason)
        if saturated and np.isfinite(value) and value > self.theta_fc_nominal + p.saturation_margin.value:
            self.excluded, self.exclusion_reason = True, "saturation_check"
            return self._result(None, "saturation_check")
        if np.isfinite(value) and value > self.theta_fc_nominal + p.above_fc_margin.value:
            self.above_fc_run += 1
            if self.above_fc_run >= int(p.above_fc_days.value):
                self.excluded, self.exclusion_reason = True, "above_fc"
                return self._result(None, "above_fc")
        elif np.isfinite(value):
            self.above_fc_run = 0
        if np.isfinite(self.drift_slope) and abs(self.drift_slope) > p.drift_slope_max.value:
            self.excluded, self.exclusion_reason = True, "drift"
            return self._result(None, "drift")

        if self.gap_days > int(p.max_gap_days.value):
            return self._result(None, "gap")
        if not np.isfinite(value):
            return self._result(None, "nodata")

        hist = np.array(self.history, dtype=float)
        win_m = hist[-int(p.missing_window_days.value) :]
        if (
            len(win_m) >= int(p.missing_window_days.value)
            and np.mean(~np.isfinite(win_m)) > p.missing_rate_max.value
        ):
            return self._result(None, "missing")
        win_f = hist[-int(p.frozen_window_days.value) :]
        if len(win_f) >= int(p.frozen_window_days.value) and np.isfinite(win_f).all():
            spread = (win_f.max() - win_f.min()) / max(abs(win_f.mean()), 1e-4) * 100.0
            if spread < p.frozen_max_variation_pct.value:
                return self._result(None, "frozen")
        return self._result(value, "ok")

    def _update_drift(self, value: float, theta_model: Optional[float]) -> None:
        """Okuma − model farkını pencereye ekler ve EKK eğimini günceller (yeterli okuma yoksa NaN)."""
        p = self.params
        win = int(p.drift_window_days.value)
        if theta_model is not None and np.isfinite(value) and p.vwc_min.value <= value <= p.vwc_max.value:
            self.residuals.append((self.day, value - float(theta_model)))
        while self.residuals and self.residuals[0][0] <= self.day - win:
            self.residuals.popleft()
        if len(self.residuals) < int(p.drift_min_points.value):
            self.drift_slope = float("nan")
            return
        tt, rr = np.array(self.residuals, dtype=float).T
        tc = tt - tt.mean()
        self.drift_slope = float(np.dot(tc, rr - rr.mean()) / np.dot(tc, tc))

    def _result(self, value: Optional[float], reason: str) -> Tuple[Optional[float], str]:
        self.last_reason = reason
        return value, reason
