"""CRITIC (Criteria Importance Through Intercriteria Correlation) Çok Kriterli Karar Verme Yöntemi.

Kaynak: Diakoulaki, Mavrotas, Papayannakis (1995). Determining objective weights in multiple criteria problems.
Uygulama:
- Kriterler:
  1. Su tüketimi (total_water_mm) -> Maliyet (minimize)
  2. Bitki stresi (cumulative_stress veya stress_days) -> Maliyet (minimize)
  3. Sulama olay sayısı (irrigation_events) -> Maliyet (minimize)
  4. Ortalama Ks (mean_ks) -> Fayda (maximize)
- Normalizasyon, standart sapma, korelasyon matrisi, bilgi miktarı C_j ve ağırlıklar w_j.
- Nihai kompozit skor ve strateji sıralaması.
"""

from typing import List, Tuple

import numpy as np
import pandas as pd


def normalize_critic_matrix(
    matrix: np.ndarray,
    benefit_mask: List[bool],
) -> np.ndarray:
    """CRITIC için karar matrisini [0, 1] aralığına normalize eder.

    Fayda (Maximize): r_ij = (x_ij - min) / (max - min)
    Maliyet (Minimize): r_ij = (max - x_ij) / (max - min)
    """
    n, m = matrix.shape
    norm = np.zeros_like(matrix, dtype=float)

    for j in range(m):
        col = matrix[:, j]
        c_min = np.min(col)
        c_max = np.max(col)
        diff = c_max - c_min
        if diff <= 1e-8:
            norm[:, j] = 1.0  # Tüm stratejiler eşitse
        else:
            if benefit_mask[j]:
                norm[:, j] = (col - c_min) / diff
            else:
                norm[:, j] = (c_max - col) / diff
    return norm


def calculate_critic_weights(
    decision_matrix: np.ndarray,
    benefit_mask: List[bool],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """CRITIC objektif ağırlıklarını hesaplar.

    Döndürür:
        (weights, info_content_c, norm_matrix)
    """
    norm_mat = normalize_critic_matrix(decision_matrix, benefit_mask)
    n, m = norm_mat.shape

    # Standart sapmalar sigma_j
    std_devs = np.std(norm_mat, axis=0, ddof=1) if n > 1 else np.ones(m)
    # Eğer sıfır varyans varsa düzelt
    std_devs = np.where(std_devs <= 1e-8, 1e-4, std_devs)

    # Korelasyon matrisi R (m x m)
    if n > 1:
        corr_matrix = np.corrcoef(norm_mat, rowvar=False)
        # NaN koruması
        corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)
    else:
        corr_matrix = np.eye(m)

    # Bilgi miktarı C_j = sigma_j * sum(1 - r_jk)
    c_scores = np.zeros(m)
    for j in range(m):
        c_scores[j] = std_devs[j] * np.sum(1.0 - corr_matrix[j, :])

    c_scores = np.maximum(c_scores, 1e-6)
    weights = c_scores / np.sum(c_scores)

    return weights, c_scores, norm_mat


def rank_strategies_critic(
    df_metrics: pd.DataFrame,
    criteria_cols: List[str] = ["total_water_mm", "cumulative_stress", "irrigation_events", "mean_ks"],
    benefit_mask: List[bool] = [False, False, False, True],
) -> pd.DataFrame:
    """Strateji metrikleri tablosunu CRITIC yöntemiyle sıralar.

    Parametreler:
        df_metrics: Strateji özet metrikleri DataFrame'i (en az 'strategy' sütunu ve kriterler).
        criteria_cols: Değerlendirilecek kriter sütun isimleri.
        benefit_mask: Her kriterin fayda (True/Maximize) veya maliyet (False/Minimize) oluşu.

    Döndürür:
        CRITIC skorları, ağırlıkları ve 'rank' sütunu eklenmiş DataFrame.
    """
    df = df_metrics.copy()
    mat = df[criteria_cols].values.astype(float)

    weights, c_scores, norm_mat = calculate_critic_weights(mat, benefit_mask)

    # Kompozit skor: S_i = sum(w_j * r_ij)
    scores = np.dot(norm_mat, weights)
    df["critic_score"] = np.round(scores, 4)

    # Ağırlık sözlüğü meta bilgi olarak atanabilir
    weights_dict = {col: round(float(w), 4) for col, w in zip(criteria_cols, weights)}
    df.attrs["critic_weights"] = weights_dict

    # Sıralama (1: En yüksek skor / En iyi strateji)
    df["rank"] = df["critic_score"].rank(ascending=False, method="min").astype(int)
    df = df.sort_values("rank").reset_index(drop=True)

    return df
