"""Simülasyon, strateji değerlendirme, CRITIC ve duyarlılık analizi modülü."""

from twin.sim.critic import calculate_critic_weights, rank_strategies_critic
from twin.sim.engine import (
    compare_all_strategies,
    prepare_season_weather,
    simulate_strategy_season,
)
from twin.sim.fault_injection import FaultConfig, inject_sensor_faults
from twin.sim.metrics import (
    SimulationMetrics,
    calculate_simulation_metrics,
    kling_gupta_efficiency,
    mean_bias_error,
    nash_sutcliffe_efficiency,
    rmse,
)
from twin.sim.plots import (
    plot_sensitivity_tornado,
    plot_strategy_comparison,
    plot_water_balance_timeseries,
)
from twin.sim.sensitivity import run_oat_sensitivity, run_sobol_morris_sampling
from twin.sim.strategies import (
    IrrigationStrategy,
    S0FixedSchedule,
    S1SensorThreshold,
    S2ETOnly,
    S3ForecastGuided,
    S4AssimilatedTwin,
    get_all_strategies,
)

__all__ = [
    "FaultConfig",
    "IrrigationStrategy",
    "S0FixedSchedule",
    "S1SensorThreshold",
    "S2ETOnly",
    "S3ForecastGuided",
    "S4AssimilatedTwin",
    "SimulationMetrics",
    "calculate_critic_weights",
    "calculate_simulation_metrics",
    "compare_all_strategies",
    "get_all_strategies",
    "inject_sensor_faults",
    "kling_gupta_efficiency",
    "mean_bias_error",
    "nash_sutcliffe_efficiency",
    "plot_sensitivity_tornado",
    "plot_strategy_comparison",
    "plot_water_balance_timeseries",
    "prepare_season_weather",
    "rank_strategies_critic",
    "rmse",
    "run_oat_sensitivity",
    "run_sobol_morris_sampling",
    "simulate_strategy_season",
]
