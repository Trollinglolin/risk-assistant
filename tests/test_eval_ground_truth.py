"""Every eval expectation must evaluate on the snapshot (catches grader bugs offline)."""

from pathlib import Path

import yaml

from hkrisk.service import RiskService

Q = Path(__file__).parents[1] / "evals" / "questions.yaml"


def test_questions_evaluate(snapshot, holdings):
    svc = RiskService(snapshot, holdings)
    cfg = yaml.safe_load(Q.read_text())
    qs = cfg["questions"]
    assert len(qs) == 65 and len({q["id"] for q in qs}) == 65
    assert sum(not q["id"].startswith("h") for q in qs) == 50  # original set unchanged
    env = {"svc": svc, "next": next, "min": min, "max": max}
    for q in qs:
        for e in q.get("expected", []):
            v = eval(e, env)
            assert isinstance(v, (int, float)), (q["id"], e)
        for t in q.get("expected_text", []):
            if t.startswith(("svc.", "max(", "min(")):
                assert isinstance(eval(t, env), str)
