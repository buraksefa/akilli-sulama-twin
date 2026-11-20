"""Matematiksel modelin analitik sonuçlarını sayısal olarak doğrular.
Hava verisi gerektirmez (sabit ETc, yağışsız). Parametreler VARSAYIMDIR (config.py ile değiştirilecek).
Çalıştır: python math_checks.py
"""
import numpy as np

# ---- varsayım parametreleri (status=assumption) ----
TH_FC, TH_WP, ZR, P_DEP, ETA = 0.32, 0.15, 0.30, 0.50, 0.75
TAW = 1000 * (TH_FC - TH_WP) * ZR          # mm
RAW = P_DEP * TAW                           # mm


def ks_fn(dr):
    return 1.0 if dr <= RAW else max(0.0, (TAW - dr) / (TAW - RAW))


def run_threshold(etc_series, bias_theta=0.0):
    """Eşik stratejisi: sensör θ_obs = θ_true + b. Günün başında sulama, sonra ETa.
    Dönüş: brüt su W, derin sızma DP, olay sayısı, ΣETa, ΣETc, stres günü."""
    delta = 1000 * ZR * bias_theta          # mm (θ yanlılığının tükenme karşılığı)
    dr, W, DP, N, ETa_sum, stress_days = 0.0, 0.0, 0.0, 0, 0.0, 0
    for c in etc_series:
        est = dr - delta                     # tahmini tükenme (θ yüksek okunursa tükenme düşük görünür)
        net = 0.0
        if est >= RAW:
            net = max(est, 0.0)              # tahmini açığı tarla kapasitesine tamamla
            W += net / ETA
            N += 1
        dr_after = dr - net
        dp = max(0.0, -dr_after)
        dr_after = max(dr_after, 0.0)
        DP += dp
        ks = ks_fn(dr_after)
        eta_a = ks * c
        ETa_sum += eta_a
        stress_days += ks < 1.0
        dr = min(dr_after + eta_a, TAW)
    return dict(W=W, DP=DP, N=N, ETa=ETa_sum, ETc=float(np.sum(etc_series)), stress_days=int(stress_days), dr_end=dr)


# ---- 1) Kütle dengesi özdeşliği: η·W = ΣETa + DP − Dr_son (Dr_baş=0) ----
etc = np.full(214, 5.0)
r0 = run_threshold(etc, 0.0)
resid = ETA * r0['W'] - (r0['ETa'] + r0['DP'] - r0['dr_end'])
print(f"[1] kütle dengesi kalıntısı: {resid:.2e} mm  (0 olmalı)")
assert abs(resid) < 1e-9

# ---- 2) Alt sınır: W_min = (ΣETc − Dr_son)/η, yağışsız, stres yok ----
wmin = (r0['ETc'] - r0['dr_end']) / ETA
print(f"[2] yanlılıksız eşik: W={r0['W']:.1f} mm, alt sınır=(ΣETc−Dr_son)/η={wmin:.1f} mm, stres günü={r0['stress_days']}, DP={r0['DP']:.2f}")
assert r0['stress_days'] == 0 and r0['DP'] < 1e-9 and abs(r0['W'] - wmin) < 1e-6

# ---- 3) Sensör yanlılığı: b<0 (kuru okur) -> fazla su; ΔW ≈ N·|δ|/η ----
for b in (-0.01, -0.02, -0.04):
    r = run_threshold(etc, b)
    delta = abs(1000 * ZR * b)
    extra_sim = r['W'] - r0['W']
    n_pred = r0['ETc'] / (RAW - delta)               # olay sayısı öngörüsü
    extra_pred = (r0['ETc'] + n_pred * delta) / ETA - r0['ETc'] / ETA   # = n·|δ|/η
    print(f"[3] b={b:+.2f}  δ={delta:4.1f} mm  olay={r['N']:2d} (öngörü {n_pred:4.1f})  "
          f"ΔW sim={extra_sim:6.1f} mm  öngörü={extra_pred:6.1f} mm  DP={r['DP']:.1f}")
    assert abs(extra_sim - extra_pred) / max(extra_sim, 1) < 0.15

# ---- 4) b>0 (ıslak okur) -> su ≈ aynı, ama stres ----
for b in (0.01, 0.02, 0.04):
    r = run_threshold(etc, b)
    print(f"[4] b={b:+.2f}  W={r['W']:.1f} mm (yanlılıksız {r0['W']:.1f})  stres günü={r['stress_days']}  ETa/ETc={r['ETa']/r['ETc']:.3f}")
    assert r['ETa'] <= r0['ETa'] + 1e-9

# ---- 5) Skaler Kalman kararlı hal: P- = (q + sqrt(q²+4qr))/2 ----
for q, r_ in [(1.0, 4.0), (0.5, 9.0), (2.0, 1.0)]:
    Pm = 1.0
    for _ in range(2000):
        Pp = Pm * r_ / (Pm + r_)
        Pm = Pp + q
    closed = (q + np.sqrt(q * q + 4 * q * r_)) / 2
    K = Pm / (Pm + r_)
    Pp_ss = Pm * r_ / (Pm + r_)
    print(f"[5] q={q}, r={r_}: P⁻ iter={Pm:.6f} kapalı={closed:.6f}  K={K:.4f}  P⁺={Pp_ss:.4f} < min(r,P⁻)={min(r_,Pm):.4f}")
    assert abs(Pm - closed) < 1e-9 and Pp_ss < min(r_, Pm)
print("tüm kontroller geçti")
