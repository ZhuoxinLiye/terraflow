"""Synthetic CPU failure receipts through actual RunFlow/SSE delivery paths.

No model, network, production graph data or GPU calls are made.
"""
import copy
import json
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.tools import StructuredTool
from lfx.mcp.flow_builder_tools.run_tools import RunFlow

from terraflow.agentic.services.assistant_service import _reconcile_flow_updates, execute_flow_with_validation_streaming
from terraflow.agentic.services.flow_types import IntentResult
from terraflow.agentic.services.project_boundaries import budget_tools

SERVICE = "terraflow.agentic.services.assistant_service"
RUNNER = "lfx.mcp.flow_builder_tools.run_tools"
FLOW = {"data": {"nodes": [{"id": "actual-query", "data": {"type": "SyntheticTool"}}], "edges": []}}


def failed_receipt(reason):
    out = {"success": False, "ok": False, "execution_blocked": True, "reason_code": reason,
           "error": {"code": reason, "candidates": [{"id": "S-F1"}, {"id": "S-F2"}]}}
    return {"error": reason, "reason_code": "tool_execution_failed", "execution_success": False,
            "vertex_results": [{"id": "actual-query", "valid": True, "run_id": "synthetic-run",
                                "data": {"outputs": {}, "logs": {}, "artifacts": {"api_run_model": {"raw": {"success": False, "outputs": out}}}}}],
            "report_evidence": {"node_results": [{"node_id": "actual-query", "success": False, "outputs": out}],
                                "trusted_tool_nodes": {"actual-query": "graph_query.query_nodes"}, "sources": []},
            "metrics": {"duration_seconds": 0.1}}


@pytest.mark.parametrize("failed", [False, True])
async def test_actual_runflow_emits_separate_receipt_and_never_proposes_failed_reuse(failed):
    receipt = failed_receipt("invalid_scope") if failed else {"result": "synthetic-success", "vertex_results": [], "metrics": {}}
    with patch(f"{RUNNER}._ensure_working_flow", return_value=copy.deepcopy(FLOW)), patch(f"{RUNNER}._emit") as emit, patch("terraflow.agentic.services.flow_run.run_working_flow", new_callable=AsyncMock, return_value=receipt), patch("terraflow.agentic.services.reusable_flows.propose_after_run", new_callable=AsyncMock, return_value=None) as proposal:
        result = await RunFlow().run_flow()
    actions = [call.args[0] for call in emit.call_args_list]
    if failed:
        assert actions == ["flow_run_failed"]
        assert emit.call_args.kwargs["report_evidence"] == receipt["report_evidence"]
        assert emit.call_args.kwargs["vertex_results"] == receipt["vertex_results"]
        assert result.data["task_success"] is False and result.data["execution_success"] is False
        proposal.assert_not_called()
    else:
        assert actions == ["flow_ran"] and "error" not in result.data
        proposal.assert_awaited_once()


@pytest.mark.parametrize("has_vertices", [False, True])
def test_failed_reconciliation_forwards_evidence_without_success_or_auto_apply(has_vertices):
    failure = {"action": "flow_run_failed", "flow_id": "synthetic-flow", **failed_receipt("invalid_scope")}
    if not has_vertices:
        failure["vertex_results"] = []
    proposal = {"action": "set_flow", "flow": copy.deepcopy(FLOW)}
    events, auto, saw_set, saw_run, _, applied = _reconcile_flow_updates(
        [proposal, failure], auto_apply_flow=False, saw_set_flow=False,
        saw_run=False, last_set_flow=None, set_flow_applied=False,
    )
    assert [e["action"] for e in events] == ["set_flow", "run_result"]
    assert not auto and saw_set and not saw_run and not applied
    assert not events[0].get("auto_apply")
    assert events[1]["execution_success"] is False and events[1]["task_success"] is False
    assert events[1]["report_evidence"] == failure["report_evidence"]


@pytest.mark.parametrize("reason", ["invalid_scope", "ambiguous_name"])
@pytest.mark.parametrize("timing", ["live", "trailing"])
async def test_failed_actual_tool_receipt_reaches_sse_and_graph_final_renderer(monkeypatch, reason, timing):
    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    receipt = failed_receipt(reason)

    async def run_flow() -> dict:
        """Execute synthetic CPU RunFlow, retaining its real failure event."""
        return await RunFlow().run_flow()

    async def engine(**kwargs):
        await budget_tools([StructuredTool.from_function(coroutine=run_flow)])[0].ainvoke({})
        if timing == "live":
            yield "tool", {"name": "run_flow", "done": True}
        yield "end", {"result": "已完成，共999条", "task_success": True}

    with patch(f"{SERVICE}._get_current_flow_summary", new_callable=AsyncMock, return_value=None), patch(f"{SERVICE}.classify_intent", new_callable=AsyncMock, return_value=IntentResult(intent="question", translation="query")), patch(f"{SERVICE}.execute_flow_file_streaming", side_effect=engine), patch(f"{RUNNER}._ensure_working_flow", return_value=copy.deepcopy(FLOW)), patch("terraflow.agentic.services.flow_run.run_working_flow", new_callable=AsyncMock, return_value=receipt), patch("terraflow.agentic.services.reusable_flows.propose_after_run", new_callable=AsyncMock) as proposal:
        events = [json.loads(e[5:]) async for e in execute_flow_with_validation_streaming(
            "TerraflowAssistant", "请查询图谱中设施 Twin Facility 的目标记录并计数。", {},
        )]
    results = [e for e in events if e["event"] == "flow_update" and e.get("action") == "run_result"]
    assert len(results) == 1 and results[0]["report_evidence"] == receipt["report_evidence"]
    assert results[0]["execution_success"] is False
    final = events[-1]["data"]
    assert final["execution_success"] is False and final["task_success"] is False
    assert reason in final["result"] and "999" not in final["result"]
    assert "S-F1" in final["result"] and "S-F2" in final["result"]
    assert final["tool_budget"]["used"] == 1
    assert not any(e["event"] == "flow_update" and e.get("action") in {"flow_ran", "flow_run_failed", "propose_plan", "set_flow"} for e in events)
    proposal.assert_not_called()


async def test_early_execution_error_without_node_results_is_still_a_failed_receipt(monkeypatch):
    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")

    async def engine(**kwargs):
        await RunFlow().run_flow()
        yield "end", {"result": "运行成功，999"}

    with patch(f"{SERVICE}._get_current_flow_summary", new_callable=AsyncMock, return_value=None), patch(f"{SERVICE}.classify_intent", new_callable=AsyncMock, return_value=IntentResult(intent="question", translation="inspect")), patch(f"{SERVICE}.execute_flow_file_streaming", side_effect=engine), patch(f"{RUNNER}._ensure_working_flow", return_value=copy.deepcopy(FLOW)), patch("terraflow.agentic.services.flow_run.run_working_flow", new_callable=AsyncMock, return_value={"error": "synthetic_timeout"}):
        events = [json.loads(e[5:]) async for e in execute_flow_with_validation_streaming("TerraflowAssistant", "调用当前项目组件读取元数据。", {})]
    final = events[-1]["data"]
    assert final["execution_success"] is False and final["task_success"] is False
    assert "synthetic_timeout" in final["result"] and "999" not in final["result"]


async def test_failed_build_attempt_does_not_start_implicit_verification_or_force_apply(monkeypatch):
    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")

    async def engine(**kwargs):
        yield "end", {"result": "已完成，共999条"}

    batches = [[{"action": "set_flow", "flow": copy.deepcopy(FLOW)},
                {"action": "flow_run_failed", "flow_id": "synthetic-flow", **failed_receipt("invalid_scope")}]]
    with patch(f"{SERVICE}._get_current_flow_summary", new_callable=AsyncMock, return_value=None), patch(f"{SERVICE}.classify_intent", new_callable=AsyncMock, return_value=IntentResult(intent="build_flow", translation="build")), patch(f"{SERVICE}.execute_flow_file_streaming", side_effect=engine), patch(f"{SERVICE}.drain_flow_events", side_effect=batches), patch(f"{SERVICE}._verify_flow_before_delivery", new_callable=AsyncMock) as verifier:
        events = [json.loads(e[5:]) async for e in execute_flow_with_validation_streaming("TerraflowAssistant", "创建图谱设施查询流程。", {}, max_retries=1)]
    verifier.assert_not_called()
    proposals = [e for e in events if e.get("event") == "flow_update" and e.get("action") == "set_flow"]
    assert len(proposals) == 1 and not proposals[0].get("auto_apply")
    assert events[-1]["data"]["execution_success"] is False
