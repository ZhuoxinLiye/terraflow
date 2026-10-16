"""Synthetic contract tests; not satellite analysis or model evaluation."""

# ruff: noqa: RUF001

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from lfx.graph.schema import ResultData
from lfx.schema.data import Data
from terraflow.agentic.flows.flow_builder_assistant import build_toolkit
from terraflow.agentic.services.assistant_service import _reconcile_flow_updates
from terraflow.agentic.services.data_catalog_tool import search_remote_sensing_data
from terraflow.agentic.services.flow_run import extract_vertex_results, run_working_flow
from terraflow.agentic.services.helpers.intent_classification import _looks_like_run_request, classify_intent
from terraflow.agentic.services.inspection_context import READ_TOOL_NAMES, inspection_only


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("只检查当前流程：scene_id 和 max_bands 是什么？不修改、不运行。", "inspect_flow"),
        ("查询色萨利有哪些 Sentinel-1 数据，只列出别运行", "inspect_flow"),
        ("运行当前工作流并返回结果", "run_flow"),
        ("创建一个工作流并运行它", "build_flow"),
    ],
)
async def test_explicit_chinese_intents_skip_classifier(text, intent):
    with patch(
        "terraflow.agentic.services.helpers.intent_classification.execute_flow_file", new_callable=AsyncMock
    ) as call:
        result = await classify_intent(text, {})
        assert result.intent == intent
        call.assert_not_called()


def test_negated_run_is_not_execution_authorization():
    assert not _looks_like_run_request("do not run the flow")
    assert not _looks_like_run_request("不要运行工作流")
    assert _looks_like_run_request("先修改参数，再运行工作流")


@pytest.mark.asyncio
async def test_mixed_edit_and_run_keeps_classifier_route():
    with patch(
        "terraflow.agentic.services.helpers.intent_classification.execute_flow_file",
        new_callable=AsyncMock,
        return_value={"result": '{"translation":"edit and run", "intent":"build_flow"}'},
    ) as classify:
        result = await classify_intent("先修改参数，再运行工作流", {})
    assert result.intent == "build_flow"
    classify.assert_awaited_once()


@pytest.mark.asyncio
async def test_inspection_toolkit_has_no_write_or_run_tools_and_context_is_isolated():
    async def inspect():
        token = inspection_only.set(True)
        try:
            names = {tool.name for tool in await build_toolkit()}
            assert names == READ_TOOL_NAMES
            await asyncio.sleep(0)
            assert inspection_only.get()
        finally:
            inspection_only.reset(token)

    async def other_request():
        await asyncio.sleep(0)
        assert not inspection_only.get()

    await asyncio.gather(inspect(), other_request())
    assert not inspection_only.get()


def test_catalog_reads_real_ids_refreshes_and_hides_synthetic(tmp_path, monkeypatch):
    monkeypatch.setenv("TERRAFLOW_WATER_RUNTIME_DIR", str(tmp_path))
    raster = tmp_path / "observed.tif"
    raster.touch()
    index = tmp_path / "scene-index.json"
    index.write_text(
        json.dumps(
            {
                "real.after": {"path": str(raster), "category": "observed", "acquired": "2023-09-13"},
                "fixture.after": {"path": str(raster), "category": "synthetic"},
            }
        )
    )
    assert [r["id"] for r in search_remote_sensing_data()["items"]] == ["real.after"]
    assert len(search_remote_sensing_data(include_test_data=True)["items"]) == 2
    item_dir = tmp_path / "catalog/collections/collection/items"
    item_dir.mkdir(parents=True)
    (item_dir / "item.json").write_text(
        json.dumps(
            {
                "id": "typed.item",
                "properties": {"workspace:data_type": "sar"},
                "assets": {"data": {"href": str(raster), "bands": [{"name": "VV"}]}},
            }
        )
    )
    record = search_remote_sensing_data("typed.item")["items"][0]
    assert not record["scene_input_available"]
    assert record["assets"][0]["available"]
    assert record["assets"][0]["bands"] == [{"name": "VV"}]
    raster.unlink()
    assert not search_remote_sensing_data("real.after")["items"][0]["available"]


def test_real_node_results_preserve_refusal_and_are_emitted_after_canvas():
    refused = {"execution_blocked": True, "reason_code": "shape_mismatch"}
    graph = SimpleNamespace(
        run_id="run-1",
        vertices=[
            SimpleNamespace(
                id="Gate-1",
                result=ResultData(results={"gate": refused}, artifacts={"type": Data}),
            )
        ],
    )
    records = extract_vertex_results(graph)
    assert records[0]["data"]["results"]["gate"] == refused
    events, *_ = _reconcile_flow_updates(
        [
            {"action": "set_flow", "flow": {"data": {"nodes": [{"id": "Gate-1"}]}}},
            {"action": "flow_ran", "flow_id": "flow-1", "vertex_results": records},
        ],
        auto_apply_flow=False,
        saw_set_flow=False,
        saw_run=False,
        last_set_flow=None,
        set_flow_applied=False,
    )
    assert [e["action"] for e in events] == ["set_flow", "run_result"]
    assert events[0]["auto_apply"] is True
    assert events[1]["vertex_results"] == records


@pytest.mark.asyncio
async def test_data_port_flow_returns_actual_tool_output_without_chat_output():
    graph = SimpleNamespace(
        run_id="run-1",
        vertices=[
            SimpleNamespace(id="Read-1", result=ResultData(results={"path": "source-path"})),
            SimpleNamespace(
                id="Inspect-1",
                result=ResultData(
                    results={"api_run_model": {"outputs": {"width": 256, "crs": "EPSG:32634"}}},
                    artifacts={"type": Data},
                ),
            ),
        ],
    )
    with (
        patch("terraflow.agentic.services.flow_run.build_graph_from_data", new_callable=AsyncMock, return_value=graph),
        patch(
            "terraflow.agentic.services.flow_run.run_graph_internal",
            new_callable=AsyncMock,
            return_value=([], "session"),
        ),
    ):
        result = await run_working_flow(
            flow_data={
                "name": "Synthetic Data-port flow",
                "data": {
                    "nodes": [],
                    "edges": [{"source": "Read-1", "target": "Inspect-1"}],
                },
            },
            flow_id="flow-1",
            user_id="user-1",
        )
    assert "EPSG:32634" in result["result"]
    assert "source-path" not in result["result"]
    assert len(result["vertex_results"]) == 2
