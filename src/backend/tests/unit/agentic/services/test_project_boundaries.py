"""Synthetic CPU boundary tests. No model, live graph data or GPU calls."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.tools import StructuredTool

from terraflow.agentic.services.project_boundaries import (
    PROJECT_GUIDANCE,
    ProjectToolBudgetExceeded,
    ToolBudget,
    budget_tools,
    constrained_project_delivery,
    obvious_scope_refusal,
    request_tool_budget,
    result_failure,
    vertex_result_failures,
)


@pytest.mark.parametrize("text", ["写一首诗", "讲个笑话", "write a poem"])
def test_explicit_unrelated_request(text):
    assert obvious_scope_refusal(text)


@pytest.mark.parametrize("text", ["为什么是0？", "这两个名字相同，怎样区分？", "没有灾前影像能下结论吗？", "继续", "公园面积能支持直升机安全起降吗？", "说明既有项目Python组件的输入要求"])
def test_contextual_and_scientific_followups_are_not_keyword_rejected(text):
    assert obvious_scope_refusal(text) is None


@pytest.mark.parametrize("value", [{"count": 0}, {"success": True, "outputs": {"count": 0, "items": []}}, {"outputs": {"observations": {"water": False}}}])
def test_zero_or_observation_false_is_not_failure(value):
    assert result_failure(value) is None


@pytest.mark.parametrize("value", [{"ok": False}, {"success": False, "outputs": None}, {"outputs": {"passed": False}}, {"outputs": {"execution_blocked": True}}])
def test_explicit_execution_failure(value):
    assert result_failure(value)


def test_raw_vertex_failure_survives_missing_outputs():
    records = [{"data": {"artifacts": {"api_run_model": {"raw": {"success": False, "error": "not_online", "outputs": None}}}}}]
    assert vertex_result_failures(records) == ["not_online"]


async def test_real_structured_tools_share_budget_across_repairs_and_async_tasks():
    executed = []

    async def lookup(item: str) -> dict:
        """Synthetic lookup."""
        executed.append(item)
        return {"count": 0}

    original = StructuredTool.from_function(coroutine=lookup)
    budget = ToolBudget(limit=2)
    token = request_tool_budget.set(budget)
    try:
        first = budget_tools([original])[0]
        assert await asyncio.create_task(first.ainvoke({"item": "first"})) == {"count": 0}
        repaired = budget_tools([original])[0]
        await repaired.ainvoke({"item": "repaired"})
        with pytest.raises(ProjectToolBudgetExceeded):
            await repaired.ainvoke({"item": "must_not_start"})
        assert executed == ["first", "repaired"]
        assert budget.used == 2 and budget.exhausted
    finally:
        request_tool_budget.reset(token)


async def test_failure_vetoes_model_completion_without_certifying_other_prose():
    async def run_flow() -> dict:
        """Synthetic failed run."""
        return {"error": "invalid_scope"}

    budget = ToolBudget()
    token = request_tool_budget.set(budget)
    try:
        await budget_tools([StructuredTool.from_function(coroutine=run_flow)])[0].ainvoke({})
    finally:
        request_tool_budget.reset(token)
    result = constrained_project_delivery({"result": "任务成功，面积999平方米", "success": True}, budget, ran=False)
    assert result["task_success"] is False
    assert result["reason_code"] == "tool_execution_failed"
    assert "999" not in result["result"]
    assert "999" in result["raw_model_response"]
    unverified = constrained_project_delivery({"result": "a generic graph answer"}, ToolBudget(), ran=True)
    assert unverified["execution_success"] is True
    assert unverified["task_success"] is None


async def test_unrelated_preflight_performs_no_model_or_canvas_calls(monkeypatch):
    from terraflow.agentic.services.assistant_service import execute_flow_with_validation_streaming

    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    with patch("terraflow.agentic.services.assistant_service.classify_intent", new_callable=AsyncMock) as classifier, patch("terraflow.agentic.services.assistant_service._get_current_flow_summary", new_callable=AsyncMock) as canvas:
        events = [event async for event in execute_flow_with_validation_streaming("FlowBuilderAssistant", "写一首诗", {})]
    classifier.assert_not_called()
    canvas.assert_not_called()
    complete = json.loads(events[-1].removeprefix("data: "))
    assert complete["data"]["result"] == PROJECT_GUIDANCE
    assert complete["data"]["task_success"] is False


async def test_stream_request_binding_is_released_after_completion(monkeypatch):
    from terraflow.agentic.services.assistant_service import execute_flow_with_validation_streaming
    from terraflow.agentic.services.flow_types import IntentResult

    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    observed = []

    async def execution(**kwargs):
        observed.append(request_tool_budget.get())
        yield "end", {"result": "缺少影像，无法计算面积。"}

    sentinel = ToolBudget(limit=3)
    token = request_tool_budget.set(sentinel)
    try:
        with patch("terraflow.agentic.services.assistant_service.classify_intent", new_callable=AsyncMock, return_value=IntentResult(intent="question", translation="missing data")), patch("terraflow.agentic.services.assistant_service._get_current_flow_summary", new_callable=AsyncMock, return_value=None), patch("terraflow.agentic.services.assistant_service.execute_flow_file_streaming", side_effect=execution):
            events = [event async for event in execute_flow_with_validation_streaming("FlowBuilderAssistant", "没有输入影像时可以计算面积吗？", {})]
        assert observed and observed[0] is not sentinel
        assert request_tool_budget.get() is sentinel
        assert '缺少影像' in json.loads(events[-1].removeprefix("data: "))["data"]["result"]
    finally:
        request_tool_budget.reset(token)


async def test_runner_fails_closed_for_raw_tool_error(monkeypatch):
    from terraflow.agentic.services.flow_run import run_working_flow

    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    records = [{"id": "synthetic", "data": {"artifacts": {"api_run_model": {"raw": {"success": False, "error": "missing_input", "outputs": None}}}}}]
    with patch("terraflow.agentic.services.flow_run.build_graph_from_data", new_callable=AsyncMock, return_value=object()), patch("terraflow.agentic.services.flow_run.run_graph_internal", new_callable=AsyncMock, return_value=([], None)), patch("terraflow.agentic.services.flow_run.extract_vertex_results", return_value=records):
        result = await run_working_flow(flow_data={"data": {"nodes": [], "edges": []}}, flow_id="synthetic", user_id="synthetic")
    assert result["task_success"] is False
    assert result["reason_code"] == "tool_execution_failed"
    assert result["vertex_results"] == records


async def test_automatic_verification_counts_runs_and_cannot_start_unbudgeted_repair(monkeypatch):
    from terraflow.agentic.services.assistant_service import _verify_flow_before_delivery

    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    budget = ToolBudget(limit=1)
    token = request_tool_budget.set(budget)
    try:
        with patch("terraflow.agentic.services.assistant_service._flow_verification_enabled", return_value=True), patch("terraflow.agentic.services.assistant_service.get_working_flow", return_value={"data": {"nodes": [{"id": "synthetic", "data": {"type": "Synthetic"}}], "edges": []}}), patch("terraflow.agentic.services.assistant_service.run_working_flow", new_callable=AsyncMock, return_value={"error": "invalid_scope"}) as run, patch("terraflow.agentic.services.assistant_service.execute_flow_file", new_callable=AsyncMock) as repair:
            result = await _verify_flow_before_delivery(flow_filename="FlowBuilderAssistant", global_variables={"FLOW_ID": "synthetic"}, user_id="synthetic", session_id=None, provider=None, model_name=None, api_key_var=None)
        assert result.status.value == "failed"
        assert budget.used == 1 and budget.run_attempts == 1 and budget.exhausted
        run.assert_awaited_once()
        repair.assert_not_called()
    finally:
        request_tool_budget.reset(token)


async def test_unknown_terrabox_source_requires_refresh_without_build_or_mutation(monkeypatch):
    import copy
    from terraflow.agentic.services.flow_run import run_working_flow

    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    flow = {"data": {"nodes": [{"id": "custom", "data": {"type": "TerraboxCustom", "node": {"template": {"code": {"value": "# a user's custom component"}}}}}], "edges": []}}
    before = copy.deepcopy(flow)
    token = request_tool_budget.set(ToolBudget())
    try:
        with patch("terraflow.agentic.services.flow_run._get_canonical_code_map", return_value={}), patch("terraflow.agentic.services.flow_run.build_graph_from_data", new_callable=AsyncMock) as build:
            result = await run_working_flow(flow_data=flow, flow_id="synthetic", user_id="synthetic")
        assert result["reason_code"] == "terrabox_budget_refresh_required"
        assert result["task_success"] is False
        build.assert_not_called()
        assert flow == before
    finally:
        request_tool_budget.reset(token)


async def test_nonstream_geo_route_uses_same_preflight_and_releases_budget(monkeypatch):
    from terraflow.agentic.services.assistant_service import execute_flow_with_validation

    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    with patch("terraflow.agentic.services.assistant_service.classify_intent", new_callable=AsyncMock) as classifier:
        result = await execute_flow_with_validation("FlowBuilderAssistant", "写一首诗", {})
    classifier.assert_not_called()
    assert result["task_success"] is False
    assert result["tool_budget"]["used"] == 0
    assert request_tool_budget.get() is None


async def test_budget_exception_yields_structured_complete_on_stream_and_nonstream(monkeypatch):
    from terraflow.agentic.services.assistant_service import execute_flow_with_validation, execute_flow_with_validation_streaming
    from terraflow.agentic.services.flow_types import IntentResult

    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    monkeypatch.setenv("TERRAFLOW_PROJECT_TOOL_BUDGET", "1")
    observed = []

    async def execution(**kwargs):
        budget = request_tool_budget.get()
        observed.append(budget)
        budget.consume("search_components")
        budget.consume("must_not_start")
        yield "end", {"result": "unreachable"}

    with patch("terraflow.agentic.services.assistant_service.classify_intent", new_callable=AsyncMock, return_value=IntentResult(intent="question", translation="query")), patch("terraflow.agentic.services.assistant_service._get_current_flow_summary", new_callable=AsyncMock, return_value=None), patch("terraflow.agentic.services.assistant_service.execute_flow_file_streaming", side_effect=execution):
        events = [event async for event in execute_flow_with_validation_streaming("FlowBuilderAssistant", "核查项目工具", {})]
        stream_result = json.loads(events[-1][5:])["data"]
        nonstream_result = await execute_flow_with_validation("FlowBuilderAssistant", "核查项目工具", {})
    for result in (stream_result, nonstream_result):
        assert result["task_success"] is False
        assert result["reason_code"] == "tool_budget_exhausted"
        assert result["tool_budget"]["used"] == 1
    assert observed[0] is not observed[1]
    assert request_tool_budget.get() is None


@pytest.mark.parametrize("kind", ["RunFlow", "SubFlow", "FlowTool"])
async def test_unverified_legacy_nested_paths_block_before_build(kind, monkeypatch):
    from terraflow.agentic.services.flow_run import run_working_flow

    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    token = request_tool_budget.set(ToolBudget())
    try:
        with patch("terraflow.agentic.services.flow_run._get_canonical_code_map", return_value={}), patch("terraflow.agentic.services.flow_run.build_graph_from_data", new_callable=AsyncMock) as build:
            result = await run_working_flow(flow_data={"data": {"nodes": [{"id": "nested", "data": {"type": kind}}], "edges": []}}, flow_id="synthetic", user_id="synthetic")
        assert result["reason_code"] == "nested_flow_budget_unverified"
        build.assert_not_called()
    finally:
        request_tool_budget.reset(token)


async def test_project_reusable_flow_reenters_runner_with_same_budget_and_legacy_upgrade(monkeypatch):
    import copy
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from lfx.interface.earthflow_terrabox import REQUEST_BUDGET_HOOK_SOURCE, TerraboxToolSpec, build_terrabox_component_source
    from terraflow.agentic.services.reusable_flows import META, execute_reusable_flow

    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    current = build_terrabox_component_source(TerraboxToolSpec("graph_query.get_item", "Synthetic", "", {"type": "object", "properties": {}}))
    legacy = current.replace(REQUEST_BUDGET_HOOK_SOURCE, "", 1)
    data = {"nodes": [{"id": "child", "data": {"type": "TerraboxGraphQueryGetItem", "node": {"template": {"code": {"value": legacy}}}}}], "edges": [], META: {"name": "synthetic child", "state": "active", "version": "synthetic-v1", "inputs": []}}
    before = copy.deepcopy(data)
    observed = []
    budget = ToolBudget(limit=4)

    @asynccontextmanager
    async def session():
        yield object()

    async def build(flow_id, payload, **kwargs):
        observed.append(request_tool_budget.get())
        assert payload["nodes"][0]["data"]["node"]["template"]["code"]["value"] == current
        return object()

    token = request_tool_budget.set(budget)
    try:
        budget.consume("run_flow")
        with patch("terraflow.agentic.services.reusable_flows.session_scope", side_effect=session), patch("terraflow.agentic.services.reusable_flows._owned", new_callable=AsyncMock, return_value=SimpleNamespace(data=data)), patch("terraflow.agentic.services.reusable_flows.snapshot_valid", return_value=True), patch("terraflow.agentic.services.reusable_flows.bind_inputs", return_value=copy.deepcopy(data)), patch("lfx.components.geo_workflow.scene_input.read_scene_index", return_value={}), patch("terraflow.agentic.services.flow_run._get_canonical_code_map", return_value={"TerraboxGraphQueryGetItem": current}), patch("terraflow.agentic.services.flow_run.build_graph_from_data", side_effect=build), patch("terraflow.agentic.services.flow_run.run_graph_internal", new_callable=AsyncMock, return_value=([], None)), patch("terraflow.agentic.services.flow_run.extract_vertex_results", return_value=[]):
            result = await execute_reusable_flow(user_id="synthetic", flow_id="synthetic", version="synthetic-v1", bindings={})
        assert observed == [budget]
        assert data == before
        assert result["evidence"]["metrics"]["budget_coverage"]["legacy_upgraded"] == ["child"]
        assert budget.used == 1
    finally:
        request_tool_budget.reset(token)


async def test_nonstream_parser_error_closes_generator_in_same_context(monkeypatch):
    from terraflow.agentic.services.assistant_service import execute_flow_with_validation

    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    closed = []
    sentinel = ToolBudget(limit=2)
    token = request_tool_budget.set(sentinel)

    async def malformed(*args, **kwargs):
        child = request_tool_budget.set(ToolBudget(limit=1))
        try:
            yield "data: invalid-json"
        finally:
            request_tool_budget.reset(child)
            closed.append(request_tool_budget.get())

    try:
        with patch("terraflow.agentic.services.assistant_service.execute_flow_with_validation_streaming", side_effect=malformed), pytest.raises(json.JSONDecodeError):
            await execute_flow_with_validation("FlowBuilderAssistant", "query", {})
        assert closed == [sentinel]
        assert request_tool_budget.get() is sentinel
    finally:
        request_tool_budget.reset(token)


async def test_nonstream_cancellation_closes_generator_without_budget_leak(monkeypatch):
    from terraflow.agentic.services.assistant_service import execute_flow_with_validation

    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    entered, hold = asyncio.Event(), asyncio.Event()
    closed = []

    async def waiting(*args, **kwargs):
        token = request_tool_budget.set(ToolBudget(limit=1))
        try:
            entered.set()
            yield 'data: {"event": "progress"}'
            await hold.wait()
        finally:
            request_tool_budget.reset(token)
            closed.append(request_tool_budget.get())

    with patch("terraflow.agentic.services.assistant_service.execute_flow_with_validation_streaming", side_effect=waiting):
        task = asyncio.create_task(execute_flow_with_validation("FlowBuilderAssistant", "query", {}))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert closed == [None]
    assert request_tool_budget.get() is None


async def test_controlled_nested_service_inherits_parent_budget_but_external_request_is_fresh(monkeypatch):
    from terraflow.agentic.services.assistant_service import execute_flow_with_validation
    from terraflow.agentic.services.flow_types import IntentResult

    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    observed = []

    async def execute(**kwargs):
        budget = request_tool_budget.get()
        observed.append(budget)
        budget.consume("synthetic_child_tool")
        yield "end", {"result": "synthetic response"}

    parent = ToolBudget(limit=5)
    token = request_tool_budget.set(parent)
    try:
        with patch("terraflow.agentic.services.assistant_service.classify_intent", new_callable=AsyncMock, return_value=IntentResult(intent="question", translation="query")), patch("terraflow.agentic.services.assistant_service._get_current_flow_summary", new_callable=AsyncMock, return_value=None), patch("terraflow.agentic.services.assistant_service.execute_flow_file_streaming", side_effect=execute):
            await asyncio.create_task(execute_flow_with_validation("TerraflowAssistant.json", "项目问题", {}, inherit_tool_budget=True))
            await execute_flow_with_validation("TerraflowAssistant.json", "项目问题", {})
        assert observed[0] is parent and observed[1] is not parent
        assert parent.used == 1
        assert request_tool_budget.get() is parent
    finally:
        request_tool_budget.reset(token)
