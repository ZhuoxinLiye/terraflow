"""Synthetic contracts and mocked execution; these are not satellite benchmarks."""

import copy
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from terraflow.agentic.services import reusable_flows as reuse
from terraflow.agentic.services.flow_run import structured_result_text
from terraflow.services.database.models.flow import Flow


def record(node_id, outputs, **raw):
    return {
        "id": node_id,
        "valid": True,
        "run_id": "synthetic-run",
        "data": {"artifacts": {"result": {"raw": {"success": True, "outputs": outputs, **raw}}}},
    }


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TERRAFLOW_WATER_RUNTIME_DIR", str(tmp_path))
    path = tmp_path / "synthetic.tif"
    path.touch()  # availability fixture only; no raster inference
    scene = {
        "path": str(path),
        "input_kind": "sar_backscatter",
        "input_scale": "linear",
        "sensor": "Sentinel-1 VV",
        "category": "observed",
    }
    catalog = {"before": scene, "after": dict(scene), "optical": {**scene, "input_kind": "reflectance"}}
    monkeypatch.setattr("lfx.components.geo_workflow.scene_input.read_scene_index", lambda: catalog)
    user = str(uuid4())
    graph = {
        "nodes": [
            {"id": "scene", "data": {"type": "SceneInput", "node": {"template": {"scene_id": {"value": "after"}}}}},
            {
                "id": "area",
                "data": {"type": "Tool", "node": {"template": {"output_path": {"value": "/old/output.tif"}}}},
            },
        ],
        "edges": [],
    }
    source = Flow(name="Synthetic SAR water analysis", data=copy.deepcopy(graph), user_id=user)
    rows = {source.id: source}

    class Session:
        async def get(self, _model, key):
            return rows.get(key)

        async def exec(self, _query):
            return SimpleNamespace(all=lambda: list(rows.values()))

        def add(self, flow):
            rows[flow.id] = flow

        async def flush(self):
            pass

    @asynccontextmanager
    async def scope():
        yield Session()

    monkeypatch.setattr(reuse, "session_scope", scope)
    monkeypatch.setattr("terraflow.agentic.services.user_components_context.current_user_id", lambda: user)
    result = {"vertex_results": [record("scene", {"path": str(path)}), record("area", {"water_area_m2": 12})]}
    return SimpleNamespace(user=user, graph=graph, source=source, rows=rows, result=result, catalog=catalog)


async def propose(env):
    return await reuse.propose_after_run(
        user_id=env.user,
        source_id=str(env.source.id),
        flow_data={"name": env.source.name, "data": env.graph},
        result=env.result,
    )


async def confirm(env, proposal, *, approve=True, **kwargs):
    return await reuse.confirm_proposal(
        proposal_id=proposal["flow_id"], source_id=str(env.source.id), user_id=env.user, approve=approve, **kwargs
    )


@pytest.mark.asyncio
async def test_draft_is_not_discoverable_until_explicit_approval(environment):
    env = environment
    proposal = await propose(env)
    assert proposal["state"] == "draft"
    assert (await reuse.search_reusable_flows("SAR"))["flows"] == []
    asset = await confirm(env, proposal)
    assert asset["state"] == "active"
    assert (await confirm(env, proposal))["flow_id"] == asset["flow_id"]
    found = (await reuse.search_reusable_flows("water"))["flows"]
    assert len(found) == 1
    assert found[0]["version"] == asset["version"]
    assert (await reuse.search_reusable_flows("", "optical"))["flows"][0]["input_conditions_match"] is False
    assert await propose(env) is None  # no duplicate on a retry


@pytest.mark.asyncio
async def test_dismissal_does_not_publish_or_allow_later_approval(environment):
    env = environment
    proposal = await propose(env)
    assert (await confirm(env, proposal, approve=False))["state"] == "dismissed"
    assert (await reuse.search_reusable_flows())["flows"] == []
    with pytest.raises(ValueError, match="proposal_dismissed"):
        await confirm(env, proposal)


@pytest.mark.asyncio
async def test_confirmation_checks_owner_canvas_and_contract_integrity(environment):
    env = environment
    proposal = await propose(env)
    for overrides, reason in [({"user_id": str(uuid4())}, "not found"), ({"source_id": str(uuid4())}, "this canvas")]:
        args = {
            "proposal_id": proposal["flow_id"],
            "source_id": str(env.source.id),
            "user_id": env.user,
            "approve": True,
        }
        args.update(overrides)
        with pytest.raises(ValueError, match=reason):
            await reuse.confirm_proposal(**args)
    asset = env.rows[next(k for k in env.rows if str(k) == proposal["flow_id"])]
    asset.data[reuse.META]["inputs"][0]["required"]["sensor"] = "changed"
    with pytest.raises(ValueError, match="snapshot_changed"):
        await confirm(env, proposal)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["error", "blocked", "missing_vertex", "missing_run_id"])
async def test_failed_blocked_or_incomplete_run_never_proposes(environment, failure):
    env = environment
    if failure == "error":
        env.result["error"] = "failed"
    elif failure == "blocked":
        env.result["vertex_results"][1] = record("area", {"execution_blocked": True})
    elif failure == "missing_vertex":
        env.result["vertex_results"].pop()
    else:
        env.result["vertex_results"][0].pop("run_id")
    assert await propose(env) is None
    assert len(env.rows) == 1


@pytest.mark.asyncio
async def test_invocations_rebind_new_input_and_paths_without_mutating_asset(environment, monkeypatch):
    env = environment
    proposal = await propose(env)
    await confirm(env, proposal)
    run = AsyncMock(return_value=env.result)
    monkeypatch.setattr("terraflow.agentic.services.flow_run.run_working_flow", run)
    results = [
        await reuse.execute_reusable_flow(
            user_id=env.user, flow_id=proposal["flow_id"], version=proposal["version"], bindings={"scene_id": scene}
        )
        for scene in ("before", "after")
    ]
    assert all(r["success"] for r in results)
    calls = [call.kwargs["flow_data"]["data"] for call in run.await_args_list]
    assert [c["nodes"][0]["data"]["node"]["template"]["scene_id"]["value"] for c in calls] == ["before", "after"]
    paths = [c["nodes"][1]["data"]["node"]["template"]["output_path"]["value"] for c in calls]
    assert paths[0] != paths[1]
    assert all("/reusable/" in p for p in paths)
    assert env.source.data == env.graph
    assert results[0]["evidence"]["invocation_id"] != results[1]["evidence"]["invocation_id"]
    for version, bindings, reason in [
        ("wrong", {"scene_id": "before"}, "version_mismatch"),
        (proposal["version"], {"scene_id": "optical"}, "conditions_mismatch"),
        (proposal["version"], {}, "bindings_mismatch"),
        (proposal["version"], {"scene_id": "missing"}, "unavailable"),
    ]:
        with pytest.raises(ValueError, match=reason):
            await reuse.execute_reusable_flow(
                user_id=env.user, flow_id=proposal["flow_id"], version=version, bindings=bindings
            )
    assert run.await_count == 2
    token = reuse._call_stack.set((proposal["flow_id"],))
    try:
        with pytest.raises(ValueError, match="recursive"):
            await reuse.execute_reusable_flow(
                user_id=env.user,
                flow_id=proposal["flow_id"],
                version=proposal["version"],
                bindings={"scene_id": "before"},
            )
    finally:
        reuse._call_stack.reset(token)


def test_large_inspection_does_not_hide_later_measurements_and_child_references():
    records = [record(str(i), {"metadata": {"long": "x" * 40000}, "bands": ["x"] * 100}) for i in range(8)]
    records.extend(
        [
            record("before", {"water_area_m2": 47362900, "threshold": -9.375}),
            record(
                "after",
                {"water_area_m2": 43987800, "threshold": -14.21875},
                flow_id="asset",
                version="v1",
                bindings={"scene_id": "after"},
                evidence={"run_ids": ["fresh-run"]},
            ),
        ]
    )
    text = structured_result_text(records)
    assert all(value in text for value in ("47362900", "43987800", "-14.21875", "fresh-run", "asset"))
    assert len(text) < 16000


@pytest.mark.asyncio
@pytest.mark.parametrize("as_list", [False, True])
async def test_failed_upstream_preflight_prevents_child_execution(monkeypatch, as_list):
    from lfx.components.geo_workflow.reusable_flow import ReusableFlowComponent
    from lfx.schema import Data

    run = AsyncMock()
    monkeypatch.setattr(reuse, "execute_reusable_flow", run)
    component = ReusableFlowComponent()
    gate = Data(data={"success": True, "outputs": {"passed": False}})
    component.set(
        preconditions=[gate] if as_list else gate,
        asset_id=str(uuid4()),
        version="v",
        bindings='{"scene_id":"before"}',
    )
    with pytest.raises(ValueError, match="preconditions_failed"):
        await component.invoke()
    run.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_exposes_actual_method_and_replaceable_example_scope(environment):
    env = environment
    env.graph["nodes"][1]["data"]["node"]["template"]["method"] = {"value": "otsu"}
    proposal = await propose(env)
    await confirm(env, proposal)
    row = (await reuse.search_reusable_flows("water"))["flows"][0]
    assert row["method_steps"][1]["parameters"]["method"] == "otsu"
    assert "replaceable" in row["binding_scope"]
    assert "code" not in row["method_steps"][1]["parameters"]


def test_canonical_version_survives_browser_integral_float_round_trip():
    data = {
        "nodes": [{"position": {"x": 10.0, "y": 0.5}}],
        "edges": [],
        reuse.META: {"inputs": [], "outputs": [], "digest_format": "canonical-v1"},
    }
    digest = reuse.graph_digest(data)
    data[reuse.META].update(graph_sha256=digest, version=digest[:16])
    data["nodes"][0]["position"]["x"] = 10
    assert reuse.snapshot_valid(data)
    data[reuse.META]["version"] = "changed"
    assert not reuse.snapshot_valid(data)


@pytest.mark.asyncio
async def test_native_single_result_list_accepts_successful_preflight(monkeypatch):
    from lfx.components.geo_workflow.reusable_flow import ReusableFlowComponent
    from lfx.schema import Data

    run = AsyncMock(return_value={"success": True, "outputs": {"water_area_m2": 12}})
    monkeypatch.setattr(reuse, "execute_reusable_flow", run)
    component = ReusableFlowComponent()
    component.set(
        preconditions=[Data(data={"success": True, "outputs": {"passed": True}})],
        asset_id=str(uuid4()),
        version="v",
        bindings='{"scene_id":"before"}',
    )
    result = await component.invoke()
    assert result.data["success"]
    run.assert_awaited_once()
    assert run.await_args.kwargs["flow_id"] == component.asset_id
