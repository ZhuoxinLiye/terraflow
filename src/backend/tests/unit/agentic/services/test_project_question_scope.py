"""Actual bundled question/generation template preparation, no model calls."""

import copy
import ast
import json
from pathlib import Path
from unittest.mock import patch
from unittest.mock import AsyncMock
from types import SimpleNamespace
import pytest

from terraflow.agentic.services.flow_preparation import load_and_prepare_flow

BUNDLED = Path(__file__).resolve().parents[4] / "base/terraflow/agentic/flows/TerraflowAssistant.json"


def prompts(flow):
    return [node["data"]["node"]["template"]["system_prompt"]["value"] for node in flow["data"]["nodes"] if node.get("data", {}).get("type") == "Agent"]


def test_actual_bundled_loader_scopes_question_and_generation_without_source_mutation(monkeypatch):
    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    before = BUNDLED.read_bytes()
    original_first, original_generator = prompts(json.loads(before))
    with patch("terraflow.agentic.services.flow_preparation.inject_lfx_components_path", side_effect=lambda x: x), patch("terraflow.agentic.services.flow_preparation.inject_assistant_fs_root", side_effect=lambda x: x):
        prepared = json.loads(load_and_prepare_flow(BUNDLED, None, None, None))
    assert BUNDLED.read_bytes() == before
    first, generator = prompts(prepared)
    assert "Earthmind project assistant" in first
    assert "Official Support Agent" not in first
    assert "Only answer questions related to Terraflow" not in first
    assert "Documentation Index" not in first
    assert "Component Generation Rules" in first and "Code Safety" in first
    assert original_first.partition("## Component Generation Rules")[2].split("## Scope & Security Rules", 1)[0] in first
    assert original_first.partition("4. **Code Safety**:")[2] in first
    from terraflow.agentic.services.project_boundaries import PROJECT_PROMPT

    assert generator == original_generator + "\n" + PROJECT_PROMPT
    for prompt in (first, generator):
        prompt = " ".join(prompt.split())
        assert "EPSG:4326 uses degrees" in prompt
        assert "water change is not verified new flooding" in prompt
        assert "safe helicopter landing" in prompt
        assert "Only handle this project's data" in prompt
    assert "Terraflow Component API Reference" in generator


def test_other_profile_and_arbitrary_json_template_unchanged(monkeypatch, tmp_path):
    original = json.loads(BUNDLED.read_text())
    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "generic")
    with patch("terraflow.agentic.services.flow_preparation.inject_lfx_components_path", side_effect=lambda x: x), patch("terraflow.agentic.services.flow_preparation.inject_assistant_fs_root", side_effect=lambda x: x):
        prepared = json.loads(load_and_prepare_flow(BUNDLED, None, None, None))
        assert prepared == original
        monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
        other = tmp_path / "TerraflowAssistant.json"
        other.write_text(json.dumps(copy.deepcopy(original)))
        assert json.loads(load_and_prepare_flow(other, None, None, None)) == original
        monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "generic")
        assert json.loads(load_and_prepare_flow(BUNDLED, None, None, None)) == original


async def test_actual_bundled_inline_main_and_child_tools_share_bound_budget(monkeypatch):
    from langchain_core.tools import StructuredTool
    from terraflow.agentic.services.project_boundaries import ProjectToolBudgetExceeded, ToolBudget, bound_budget_tools, request_tool_budget
    from terraflow.agentic.services.flow_preparation import inject_project_assistant_scope

    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    prepared = inject_project_assistant_scope(json.loads(BUNDLED.read_text()))
    executed = []

    def read(value: str) -> str:
        """Synthetic URL/keyword reader."""
        executed.append(value)
        return value

    original = StructuredTool.from_function(read, return_direct=True, metadata={"source": "synthetic"}, tags=["retained"])
    budget = ToolBudget(limit=2)
    token = request_tool_budget.set(budget)
    try:
        for node in prepared["data"]["nodes"]:
            if node.get("data", {}).get("type") != "Agent":
                continue
            code = node["data"]["node"]["template"]["code"]["value"]
            cls = next(n for n in ast.parse(code).body if isinstance(n, ast.ClassDef))
            method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_agent_requirements")
            namespace = {"get_llm": lambda **kw: "synthetic-model", "logger": SimpleNamespace(adebug=AsyncMock()), "Message": type("Message", (), {})}
            exec(compile(ast.Module(body=[method], type_ignores=[]), "<actual-bundled-inline-agent>", "exec"), namespace)  # noqa: S102
            agent = SimpleNamespace(model=[], user_id="synthetic", api_key="synthetic", get_memory_data=AsyncMock(return_value=[]), add_current_date_tool=False, tools=[original], set_tools_callbacks=lambda *a: None, _get_shared_callbacks=lambda: [])
            _, _, tools = await namespace["get_agent_requirements"](agent)
            assert tools[0].return_direct is True
            assert tools[0].metadata["source"] == "synthetic" and tools[0].tags == ["retained"]
            assert bound_budget_tools(tools)[0] is tools[0]
            await tools[0].ainvoke({"value": node["id"]})
        with pytest.raises(ProjectToolBudgetExceeded):
            await tools[0].ainvoke({"value": "must_not_execute"})
        assert len(executed) == 2 and budget.used == 2
    finally:
        request_tool_budget.reset(token)


def test_inline_anchor_change_refuses_unbudgeted_request(monkeypatch):
    from terraflow.agentic.services.flow_preparation import inject_project_assistant_scope

    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    source = json.loads(BUNDLED.read_text())
    node = next(n for n in source["data"]["nodes"] if n.get("data", {}).get("type") == "Agent")
    node["data"]["node"]["template"]["code"]["value"] = "# unexpected replacement"
    with pytest.raises(ValueError, match="tool-budget anchor changed"):
        inject_project_assistant_scope(source)


async def test_wrapper_retains_artifact_protocol_and_generic_unbound_noop(monkeypatch):
    from langchain_core.tools import StructuredTool
    from terraflow.agentic.services.project_boundaries import ToolBudget, bound_budget_tools, request_tool_budget

    def artifact(value: str):
        """Synthetic artifact tool."""
        return "content:" + value, {"source_id": value}

    original = StructuredTool.from_function(artifact, response_format="content_and_artifact", return_direct=True)
    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    assert bound_budget_tools([original])[0] is original
    budget = ToolBudget(limit=1)
    token = request_tool_budget.set(budget)
    try:
        wrapped = bound_budget_tools([original])[0]
        message = await wrapped.ainvoke({"type": "tool_call", "name": original.name, "args": {"value": "synthetic"}, "id": "outer"})
        assert message.content == "content:synthetic" and message.artifact == {"source_id": "synthetic"}
        assert wrapped.return_direct and wrapped.response_format == "content_and_artifact" and budget.used == 1
        monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "generic")
        assert bound_budget_tools([original])[0] is original
    finally:
        request_tool_budget.reset(token)


async def test_wrapper_preserves_handled_tool_error_status_and_injected_call_id(monkeypatch):
    from typing import Annotated
    from langchain_core.tools import InjectedToolCallId, StructuredTool, ToolException
    from terraflow.agentic.services.project_boundaries import ToolBudget, bound_budget_tools, request_tool_budget

    def failure(value: str):
        """Synthetic handled failure."""
        raise ToolException("synthetic offline")

    def injected(value: str, tool_call_id: Annotated[str, InjectedToolCallId]):
        """Synthetic tool with actual call ID injection."""
        return value, {"actual_call_id": tool_call_id}

    original_error = StructuredTool.from_function(failure, response_format="content_and_artifact", handle_tool_error=True)
    original_id = StructuredTool.from_function(injected, response_format="content_and_artifact")
    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    budget = ToolBudget(limit=3)
    token = request_tool_budget.set(budget)
    try:
        error, identifier = bound_budget_tools([original_error, original_id])
        message = await error.ainvoke({"type": "tool_call", "name": error.name, "args": {"value": "x"}, "id": "real-error-id"})
        assert message.status == "error" and message.tool_call_id == "real-error-id"
        actual = await identifier.ainvoke({"type": "tool_call", "name": identifier.name, "args": {"value": "x"}, "id": "real-injected-id"})
        assert actual.status == "success" and actual.tool_call_id == "real-injected-id"
        assert actual.artifact["actual_call_id"] == "real-injected-id"
        synchronous = identifier.invoke({"type": "tool_call", "name": identifier.name, "args": {"value": "x"}, "id": "real-sync-id"})
        assert synchronous.artifact["actual_call_id"] == "real-sync-id"
        assert budget.used == 3
    finally:
        request_tool_budget.reset(token)
