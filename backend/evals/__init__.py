"""Eval harness: YAML cases, seven-dimension grader, markdown report.

Approach (kept boring on purpose):
  1. Seed the fixture world named in the case.
  2. Run the same AgentLoop the API uses (FakeLLM script or a real model).
  3. Grade the trace + the DATABASE, never the agent's self-report.
  4. Repeat N times and report stability as the share of repeats that
     match the modal (decision, pass-vector).
"""
