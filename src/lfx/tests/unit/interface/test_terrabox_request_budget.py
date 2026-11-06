"""Synthetic HTTP stubs exercise canonical generated code, not live model behavior."""

import ast
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
import pytest
from lfx.interface.earthflow_terrabox import REQUEST_BUDGET_HOOK_SOURCE, TerraboxToolSpec, build_terrabox_component_source, scientific_precondition_error
from terraflow.agentic.services.project_boundaries import ToolBudget, prepare_terrabox_budget_payload, request_tool_budget


def generated_execute(slug, source_override=None):
    source = ast.parse(source_override or build_terrabox_component_source(TerraboxToolSpec(slug, "Synthetic", "", {"type": "object", "properties": {}})))
    cls = next(node for node in source.body if isinstance(node, ast.ClassDef))
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_execute")
    namespace = {"Any": object, "requests": requests, "scientific_precondition_error": scientific_precondition_error}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<canonical-generated-execute>", "exec"), namespace)  # noqa: S102
    component = SimpleNamespace(preconditions=None, _TERRABOX_SLUG=slug, _api_key_value=lambda: "synthetic-test-key", _base_url_value=lambda: "http://synthetic.invalid")
    return lambda: namespace["_execute"](component, {})


async def test_actual_http_count_shared_across_nodes_async_and_copied_threads(monkeypatch):
    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    first, second = generated_execute("graph_query.get_item"), generated_execute("graph_query.query_nodes")
    response = Mock()
    response.json.return_value = {"success": True, "outputs": {"count": 0}}
    budget = ToolBudget(limit=3)
    token = request_tool_budget.set(budget)
    try:
        budget.consume("run_flow")
        with patch("requests.post", return_value=response) as post:
            assert (await asyncio.to_thread(first))["success"] is True
            assert (await asyncio.create_task(asyncio.to_thread(second)))["success"] is True
            blocked = first()
            assert blocked["outputs"]["reason_code"] == "tool_budget_exhausted"
            assert post.call_count == 2
        assert budget.summary() == {"limit": 3, "used": 3, "exhausted": True, "run_attempts": 1, "scientific_http_calls": 2, "discovery_or_edit_calls": 0}
    finally:
        request_tool_budget.reset(token)


def test_generic_profile_and_unbound_canvas_calls_unchanged(monkeypatch):
    execute = generated_execute("graph_query.get_item")
    response = Mock()
    response.json.return_value = {"success": True}
    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "generic")
    budget = ToolBudget(limit=1)
    token = request_tool_budget.set(budget)
    try:
        with patch("requests.post", return_value=response) as post:
            execute()
            execute()
            assert post.call_count == 2 and budget.used == 0
    finally:
        request_tool_budget.reset(token)
    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    with patch("requests.post", return_value=response) as post:
        execute()
        assert post.call_count == 1


async def test_legacy_current_and_custom_source_treatment_without_double_charge(monkeypatch):
    import copy

    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    current = build_terrabox_component_source(TerraboxToolSpec("graph_query.get_item", "Synthetic", "", {"type": "object", "properties": {}}))
    legacy = current.replace(REQUEST_BUDGET_HOOK_SOURCE, "", 1)

    def payload(code):
        return {"nodes": [{"id": "synthetic", "data": {"type": "TerraboxGraphQueryGetItem", "node": {"template": {"code": {"value": code}}}}}], "edges": []}

    original = payload(legacy)
    before = copy.deepcopy(original)
    prepared, coverage = prepare_terrabox_budget_payload(original, {})
    assert original == before
    assert coverage["legacy_upgraded"] == ["synthetic"]
    assert coverage["complete_for_generated_terrabox"] is True
    upgraded = prepared["nodes"][0]["data"]["node"]["template"]["code"]["value"]
    assert upgraded == current
    again, current_coverage = prepare_terrabox_budget_payload(payload(current), {})
    assert current_coverage["legacy_upgraded"] == []
    assert again == payload(current)
    custom = payload(legacy + "\n# user custom modification\n")
    custom_before = copy.deepcopy(custom)
    retained, unknown = prepare_terrabox_budget_payload(custom, {})
    assert retained == custom_before and custom == custom_before
    assert unknown["unknown"] == ["synthetic"]
    assert unknown["complete_for_generated_terrabox"] is False

    # Both upgraded old source and current source charge exactly once per HTTP.
    for source in (upgraded, current):
        execute = generated_execute("graph_query.get_item", source)
        budget = ToolBudget(limit=1)
        token = request_tool_budget.set(budget)
        response = Mock()
        response.json.return_value = {"success": True, "outputs": {"count": 0}}
        try:
            with patch("requests.post", return_value=response) as post:
                assert execute()["success"] is True
                assert execute()["success"] is False
                assert post.call_count == 1
            assert budget.used == 1
        finally:
            request_tool_budget.reset(token)


@pytest.mark.parametrize('declared,expected', [(7500, 7500), (True, 60), (-1, 60), ('7500', 60)])
def test_generated_timeout_follows_bounded_tool_contract(declared, expected):
    """A long-running remote tool must not silently inherit a 60-second timeout."""
    source = build_terrabox_component_source(TerraboxToolSpec('segearth.detect', 'Synthetic', '', {
        'type': 'object', 'properties': {}, 'x-request-timeout-seconds': declared}))
    assert f'value={expected}, advanced=True)' in source
    execute = generated_execute('segearth.detect', source_override=source)
    response = Mock()
    response.json.return_value = {'success': True}
    with patch('requests.post', return_value=response) as post:
        assert execute()['success']
        assert post.call_args.kwargs['timeout'] == expected
        assert post.call_count == 1
