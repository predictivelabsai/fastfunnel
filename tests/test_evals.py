import json
from pathlib import Path

from evals.run_eval import CASES_PATH, evaluate_case


def test_all_agent_eval_cases_pass():
    cases = json.loads(CASES_PATH.read_text())["cases"]
    assert cases
    assert all(evaluate_case(case)["passed"] for case in cases)


def test_eval_cases_cover_policy_and_groundedness():
    cases = json.loads(Path(CASES_PATH).read_text())["cases"]
    categories = {case["category"] for case in cases}
    assert {"strategy", "policy", "groundedness"} <= categories
