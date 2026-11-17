import pytest

from browserrig.input import HumanMotor, Instant, WheelStep


def test_human_wheel_plan_starts_and_ends_gently():
    plan = HumanMotor().wheel_steps(delta_x=-60, delta_y=600)
    assert sum(step.delta_x for step in plan) == pytest.approx(-60)
    assert sum(step.delta_y for step in plan) == pytest.approx(600)
    assert sum(step.delay_before_seconds for step in plan) == pytest.approx(
        0.546, abs=0.001
    )
    deltas = [step.delta_y for step in plan]
    assert all(delta > 0 for delta in deltas)
    assert deltas.index(max(deltas)) == len(deltas) // 2
    assert deltas[0] < 1 and deltas[-1] < 1 and max(deltas) < 35


@pytest.mark.parametrize("speed", [0.5, 2])
def test_scroll_speed_changes_motor_timing_without_changing_distance(speed):
    normal = HumanMotor().wheel_steps(delta_x=60, delta_y=-600)
    adjusted = HumanMotor(scroll_speed=speed).wheel_steps(delta_x=60, delta_y=-600)
    normal_seconds = sum(step.delay_before_seconds for step in normal)
    assert sum(step.delay_before_seconds for step in adjusted) == pytest.approx(
        normal_seconds / speed
    )
    assert sum(step.delta_x for step in adjusted) == pytest.approx(60)
    assert sum(step.delta_y for step in adjusted) == pytest.approx(-600)


@pytest.mark.parametrize("distance,seconds", [(10, 0.2), (50_000, 1.5)])
def test_human_wheel_timing_has_bounded_defaults(distance, seconds):
    plan = HumanMotor().wheel_steps(delta_x=0, delta_y=distance)
    assert sum(step.delay_before_seconds for step in plan) == pytest.approx(seconds)


@pytest.mark.parametrize("speed", [0, -1, float("inf"), float("nan")])
def test_invalid_scroll_speed_is_rejected(speed):
    with pytest.raises(ValueError, match="scroll_speed"):
        HumanMotor(scroll_speed=speed)


def test_instant_wheel_plan_has_one_step_without_delay():
    assert Instant().wheel_steps(delta_x=-60, delta_y=600) == (
        WheelStep(delta_x=-60, delta_y=600),
    )


@pytest.mark.parametrize("delay", [-0.1, float("inf"), float("nan")])
def test_invalid_wheel_delay_is_rejected(delay):
    with pytest.raises(ValueError, match="Wheel delay"):
        WheelStep(delta_x=0, delta_y=600, delay_before_seconds=delay)


@pytest.mark.parametrize("delta_x,delta_y", [(float("inf"), 0), (0, float("nan"))])
def test_nonfinite_wheel_deltas_are_rejected(delta_x, delta_y):
    with pytest.raises(ValueError, match="Wheel deltas"):
        WheelStep(delta_x=delta_x, delta_y=delta_y)
