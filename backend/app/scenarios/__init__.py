"""Four assignment scenarios plus cheap one-click insights."""

from app.scenarios.catalogue import SCENARIOS, ScenarioSpec, get_scenario, list_scenarios
from app.scenarios.runner import execute_scenario

__all__ = ["SCENARIOS", "ScenarioSpec", "get_scenario", "list_scenarios", "execute_scenario"]
