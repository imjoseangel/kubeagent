from app.agents.steer import DIAGNOSIS_COMPLETE_MARKER, Trail


def test_record_appends_step_and_reports_progress() -> None:
    trail = Trail(max_hops=8)

    note = trail.record("get_pods")

    assert trail.steps == ["get_pods"]
    assert "1/8 hops" in note


def test_repeated_step_is_flagged_as_looping_and_not_appended_again() -> None:
    trail = Trail(max_hops=8)
    trail.record("get_pods")

    note = trail.record("get_pods")

    assert "looping" in note
    assert trail.steps == ["get_pods"]


def test_nudges_toward_convergence_near_budget() -> None:
    trail = Trail(max_hops=4)
    trail.record("a")

    note = trail.record("b")

    assert "start converging" in note


def test_forces_convergence_once_budget_is_spent() -> None:
    trail = Trail(max_hops=2)
    trail.record("a")

    note = trail.record("b")

    assert "Hop budget spent" in note
    assert DIAGNOSIS_COMPLETE_MARKER in note


def test_accepts_and_mutates_a_shared_external_steps_list() -> None:
    shared: list[str] = []
    trail = Trail(max_hops=8, steps=shared)

    trail.record("get_pods")

    assert shared == ["get_pods"]
