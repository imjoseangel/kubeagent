from unittest.mock import patch

from llama_index.core.tools import FunctionTool

from app.agents.steer import Trail
from app.kube.read_tools import make_read_tools


def _tool(tools: list[FunctionTool], name: str) -> FunctionTool:
    return next(t for t in tools if t.metadata.name == name)


async def test_get_pods_records_trail_and_returns_envelope() -> None:
    # GIVEN a fresh trail and an API call that succeeds
    trail = Trail(max_hops=8)
    tools = make_read_tools(trail, "staging", ["staging"])

    # WHEN get_pods is called
    with patch(
        "app.kube.read_tools.api.list_pods", return_value="pod-a  Running"
    ):
        output = await _tool(tools, "get_pods").acall()

    # THEN the envelope carries the output plus a steer note, and the step
    # is recorded on the trail
    result = output.raw_output
    assert result["tool"] == "get_pods"
    assert "pod-a" in result["summary"]
    assert "[steer]" in result["summary"]
    assert trail.steps == ["get_pods"]


async def test_get_pods_denied_returns_error_envelope_without_recording() -> (
    None
):
    # GIVEN a namespace outside the allowlist
    trail = Trail(max_hops=8)
    tools = make_read_tools(trail, "staging", ["other"])

    # WHEN get_pods is called THEN the denial is surfaced by the namespace
    # guard and no trail step is recorded — without ever hitting the API
    with patch("app.kube.read_tools.api.list_pods") as mocked:
        output = await _tool(tools, "get_pods").acall()

    mocked.assert_not_called()
    result = output.raw_output
    assert result["summary"] == "Denied."
    assert "not in scope" in result["error"]
    assert trail.steps == []


async def test_describe_pod_passes_pod_argument_through() -> None:
    trail = Trail(max_hops=8)
    tools = make_read_tools(trail, "staging", ["staging"])

    with patch(
        "app.kube.read_tools.api.describe_pod", return_value="Events: OK"
    ) as mocked:
        output = await _tool(tools, "describe_pod").acall(pod="web-1")

    mocked.assert_called_once_with("staging", "web-1")
    assert output.raw_output["parsed"] == {"pod": "web-1"}


async def test_get_logs_passes_previous_and_container_through() -> None:
    trail = Trail(max_hops=8)
    tools = make_read_tools(trail, "staging", ["staging"])

    with patch(
        "app.kube.read_tools.api.pod_logs", return_value="log line"
    ) as mocked:
        await _tool(tools, "get_logs").acall(
            pod="web-1", previous=True, container="app"
        )

    mocked.assert_called_once_with("staging", "web-1", True, "app")


async def test_get_rollout_history_passes_deployment_through() -> None:
    trail = Trail(max_hops=8)
    tools = make_read_tools(trail, "staging", ["staging"])

    with patch(
        "app.kube.read_tools.api.deployment_detail", return_value="{}"
    ) as mocked:
        await _tool(tools, "get_rollout_history").acall(deployment="web")

    mocked.assert_called_once_with("staging", "web")


async def test_repeated_call_triggers_loop_steer() -> None:
    trail = Trail(max_hops=8)
    tools = make_read_tools(trail, "staging", ["staging"])
    tool = _tool(tools, "get_pods")

    with patch("app.kube.read_tools.api.list_pods", return_value="ok"):
        await tool.acall()
        second = await tool.acall()

    assert "looping" in second.raw_output["summary"]
