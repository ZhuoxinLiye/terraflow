# Chinese interface text intentionally uses Chinese punctuation.
# ruff: noqa: RUF001
"""User-owned, versioned flow assets in the existing Flow table.

Drafts are created only from successful executions. Publication is a separate
user confirmation handled outside the model toolkit. Execution binds declared
catalog inputs into a copy, verifies the snapshot, and records fresh evidence.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlmodel import select

from terraflow.services.database.models.flow import Flow
from terraflow.services.deps import session_scope

MAX_INPUTS = 8
MAX_NESTING = 3
META = "reusable_flow"
DRAFT_TAG = "reusable-flow:draft"
ACTIVE_TAG = "reusable-flow"
APPROVE = "Approve reusable flow: "
DISMISS = "Dismiss reusable flow: "
_call_stack: ContextVar[tuple[str, ...]] = ContextVar("reusable_flow_stack", default=())


def graph_digest(data: dict) -> str:
    payload = {k: data.get(k, []) for k in ("nodes", "edges")}
    # Bind the input/output contract to the immutable version as well.
    if data.get(META):
        payload["contract"] = {k: data[META].get(k) for k in ("inputs", "outputs")}
    if (data.get(META) or {}).get("digest_format") == "canonical-v1":
        payload = _canonical_numbers(payload)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _canonical_numbers(value):
    # Browsers serialize 10.0 as 10. Treat that round-trip as the same value.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _canonical_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canonical_numbers(v) for v in value]
    return value


def snapshot_valid(data: dict) -> bool:
    meta = data.get(META) or {}
    digest = graph_digest(data)
    return digest == meta.get("graph_sha256") and meta.get("version") == digest[:16]


def node_outputs(records: list[dict]) -> list[dict]:
    """Keep scientific data, drop serialized tool schemas and file manifests."""
    rows = []
    for record in records:
        artifacts = record.get("data", {}).get("artifacts") or record.get("artifacts") or {}
        for port, artifact in artifacts.items():
            raw = artifact.get("raw") if isinstance(artifact, dict) else None
            if not isinstance(raw, dict) or port == "api_build_tool":
                continue
            outputs = raw.get("outputs")
            if outputs is None and "results" in raw:  # reusable subflow result
                outputs = raw
            if isinstance(outputs, dict):
                row = {"node_id": record["id"], "port": port, "success": raw.get("success", True), "outputs": outputs}
                if "flow_id" in raw:
                    row["invocation"] = {k: raw.get(k) for k in ("flow_id", "version", "bindings", "error")}
                    row["invocation"]["evidence"] = {
                        k: raw.get("evidence", {}).get(k) for k in ("invocation_id", "run_ids", "metrics")
                    }
                rows.append(row)
    return rows


def successful_run(result: dict) -> bool:
    records = result.get("vertex_results") or []
    if result.get("error") or not records or not all(r.get("valid") for r in records):
        return False
    return not any(
        row.get("success") is False
        or row["outputs"].get("success") is False
        or row["outputs"].get("passed") is False
        or row["outputs"].get("execution_blocked")
        for row in node_outputs(records)
    )


def input_contract(data: dict, catalog: dict) -> list[dict]:
    """First supported contract: catalog-backed SceneInput bindings.

    Other graph families remain ordinary flows until they have an explicit
    binding adapter. A guessed path is never exposed as a reusable interface.
    """
    slots = []
    for node in data.get("nodes", []):
        if node.get("data", {}).get("type") != "SceneInput":
            continue
        value = node["data"]["node"]["template"]["scene_id"].get("value")
        scene = catalog.get(value)
        if not scene:
            message = "SceneInput is not backed by the current catalog"
            raise ValueError(message)
        required = {k: scene[k] for k in ("input_kind", "input_scale", "sensor", "category") if scene.get(k)}
        if not required.get("input_kind"):
            message = "Scene input has no declared input_kind"
            raise ValueError(message)
        slots.append(
            {
                "name": "scene_id" if not slots else f"scene_id_{len(slots) + 1}",
                "node_id": node["id"],
                "field": "scene_id",
                "required": required,
            }
        )
    if not slots or len(slots) > MAX_INPUTS:
        message = "This flow has no supported catalog input contract"
        raise ValueError(message)
    return slots


def bind_inputs(data: dict, slots: list[dict], bindings: dict, catalog: dict, invocation_id: str) -> dict:
    if set(bindings) != {slot["name"] for slot in slots}:
        message = "input_bindings_mismatch"
        raise ValueError(message)
    bound = copy.deepcopy(data)
    by_id = {node["id"]: node for node in bound["nodes"]}
    for slot in slots:
        scene = catalog.get(bindings[slot["name"]])
        if not scene or not Path(scene.get("path", "")).is_file():
            message = "scene_unavailable"
            raise ValueError(message)
        if any(scene.get(k) != v for k, v in slot["required"].items()):
            message = "input_conditions_mismatch"
            raise ValueError(message)
        by_id[slot["node_id"]]["data"]["node"]["template"][slot["field"]]["value"] = bindings[slot["name"]]
    # An invocation gets fresh files. Never replay the saved output path.
    runtime = os.getenv("TERRAFLOW_WATER_RUNTIME_DIR")
    if not runtime:
        message = "runtime_unavailable"
        raise ValueError(message)
    output_dir = Path(runtime) / "canvas-runs" / "reusable" / invocation_id
    for node in bound["nodes"]:
        template = node.get("data", {}).get("node", {}).get("template", {})
        if isinstance(template.get("output_path"), dict):
            output_dir.mkdir(parents=True, exist_ok=True)
            suffix = Path(str(template["output_path"].get("value") or "")).suffix.lower()
            if suffix not in {".tif", ".tiff", ".json", ".geojson", ".csv", ".png"}:
                suffix = ".tif"
            template["output_path"]["value"] = str(output_dir / f"{uuid4().hex}{suffix}")
    return bound


def asset_summary(flow: Flow) -> dict:
    meta = (flow.data or {}).get(META) or {}
    # Expose the method, not the example's numeric result or tool schemas.
    fields = {
        "method",
        "input_transform",
        "otsu_range",
        "direction",
        "foreground_value",
        "background_value",
        "nodata_value",
        "field_path",
    }
    steps = [
        {
            "component_type": node.get("data", {}).get("type"),
            "parameters": {
                key: value.get("value")
                for key, value in node.get("data", {}).get("node", {}).get("template", {}).items()
                if key in fields and isinstance(value, dict)
            },
        }
        for node in (flow.data or {}).get("nodes", [])
    ]
    return {
        "flow_id": str(flow.id),
        "name": meta.get("name", flow.name),
        "version": meta.get("version"),
        "description": flow.description,
        "method_steps": steps,
        "binding_scope": (
            "SceneInput values are replaceable inputs. Dates/places in the name describe "
            "the successful example, not a restriction. This method may cover only part of a larger task."
        ),
        "inputs": meta.get("inputs"),
        "outputs": meta.get("outputs"),
        "validation": meta.get("validation"),
        "component_type": "ReusableFlow",
        "state": meta.get("state"),
    }


async def _owned(session, flow_id: str, user_id: str) -> Flow:
    flow = await session.get(Flow, UUID(flow_id))
    if not flow or str(flow.user_id) != str(user_id):
        message = "Flow not found"
        raise ValueError(message)
    return flow


async def propose_after_run(*, user_id: str, source_id: str, flow_data: dict, result: dict) -> dict | None:
    if not user_id or not successful_run(result):
        return None
    from lfx.components.geo_workflow.scene_input import read_scene_index

    data = copy.deepcopy(flow_data.get("data") or {})
    try:
        slots = input_contract(data, read_scene_index())
    except ValueError:
        return None
    records = result["vertex_results"]
    if {r["id"] for r in records} != {n["id"] for n in data.get("nodes", [])}:
        return None
    if not all(r.get("run_id") for r in records):
        return None
    outputs = [
        {"node_id": row["node_id"], "port": row["port"], "fields": sorted(row["outputs"])}
        for row in node_outputs(records)
    ]
    data[META] = {"inputs": slots, "outputs": outputs, "digest_format": "canonical-v1"}
    # Version covers the graph and its binding contract, excluding mutable state.
    digest = graph_digest(data)
    name = flow_data.get("name") or "遥感分析流程"
    async with session_scope() as session:
        source = await _owned(session, source_id, user_id)
        if (source.data or {}).get(META):
            return None
        rows = (await session.exec(select(Flow).where(Flow.user_id == UUID(user_id)))).all()
        if any(
            (f.data or {}).get(META, {}).get("graph_sha256") == digest
            and (f.data or {}).get(META, {}).get("state") in {"active", "draft"}
            for f in rows
        ):
            return None
        run_ids = sorted({r["run_id"] for r in result["vertex_results"] if r.get("run_id")})
        meta = {
            "state": "draft",
            "name": name,
            "source_flow_id": source_id,
            "version": digest[:16],
            "graph_sha256": digest,
            "digest_format": "canonical-v1",
            "inputs": slots,
            "outputs": outputs,
            "validation": {
                "depth": "one_local_execution",
                "run_ids": run_ids,
                "date": datetime.now(timezone.utc).isoformat(),
                "limitations": "单次执行通过不证明精度、跨事件有效性或洪水成因。",
            },
        }
        data[META] = meta
        draft = Flow(
            name=f"待确认 · {name} · {uuid4().hex[:6]}",
            description=source.description,
            data=data,
            user_id=UUID(user_id),
            folder_id=source.folder_id,
            tags=[DRAFT_TAG],
            locked=True,
        )
        session.add(draft)
        await session.flush()
        proposal = asset_summary(draft)
    requirements = json.dumps([s["required"] for s in slots], ensure_ascii=False)
    proposal["markdown"] = (
        f"### 保存为可复用流程\n\n**{name}**\n\n"
        f"输入：{', '.join(s['name'] for s in slots)}（每次绑定目录影像）。\n\n"
        f"适用条件：`{requirements}`。每次调用重新检查输入，重新执行并计算数据相关参数。\n\n"
        "输出：原流程的工具结果、测量值和本次运行证据。"
        "已保留这次成功记录，单次通过不代表科学精度验证。\n\n"
        "同意后加入现有工作流列表，后续任务可检索并作为子流程引用；暂不保存不会发布。"
    )
    return proposal


async def confirm_proposal(*, proposal_id: str, source_id: str, user_id: str, approve: bool) -> dict:
    async with session_scope() as session:
        flow = await _owned(session, proposal_id, user_id)
        data = copy.deepcopy(flow.data or {})
        meta = data.get(META) or {}
        if meta.get("source_flow_id") != source_id or meta.get("state") not in {"draft", "active", "dismissed"}:
            message = "Proposal does not belong to this canvas"
            raise ValueError(message)
        if not snapshot_valid(data):
            message = "snapshot_changed"
            raise ValueError(message)
        if meta["state"] == "active":
            return asset_summary(flow)  # approval retries are idempotent
        if meta["state"] == "dismissed":
            if approve:
                message = "proposal_dismissed"
                raise ValueError(message)
            return asset_summary(flow)
        meta["state"] = "active" if approve else "dismissed"
        data[META] = meta
        flow.data = data
        flow.tags = [ACTIVE_TAG if approve else "reusable-flow:dismissed"]
        flow.name = f"{meta['name']} · {meta['version']} · {str(flow.id)[:6]}"
        session.add(flow)
        return asset_summary(flow)


async def search_reusable_flows(query: str = "", scene_id: str = "") -> dict:
    """Find approved reusable analysis flows for a task or subtask.

    Returns real IDs, pinned versions, input bindings and observed conditions.
    Search BEFORE rebuilding common analysis chains. This never executes a flow.
    """
    from lfx.components.geo_workflow.scene_input import read_scene_index

    from terraflow.agentic.services.user_components_context import current_user_id

    user_id = current_user_id()
    if not user_id:
        return {"flows": []}
    async with session_scope() as session:
        rows = (await session.exec(select(Flow).where(Flow.user_id == UUID(user_id)))).all()
        terms = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", query.lower())
        candidates = []
        for flow in rows:
            meta = (flow.data or {}).get(META) or {}
            if meta.get("state") != "active" or not snapshot_valid(flow.data):
                continue
            haystack = json.dumps(asset_summary(flow), ensure_ascii=False).lower()
            score = sum(t in haystack for t in terms)
            if terms and not score:
                continue
            row = asset_summary(flow)
            if scene_id:
                scene = read_scene_index().get(scene_id) or {}
                row["input_conditions_match"] = all(
                    scene.get(k) == v for slot in meta["inputs"] for k, v in slot["required"].items()
                )
            candidates.append((score, row))
    return {
        "flows": [row for _, row in sorted(candidates, key=lambda x: -x[0])[:10]],
        "usage": (
            "Use ReusableFlow nodes; set asset_id to returned flow_id and pin version. "
            "Set bindings to a JSON object keyed by "
            "inputs.name. result is Data with outputs, results, and evidence. Never copy a prior numeric result."
        ),
    }


async def execute_reusable_flow(*, user_id: str, flow_id: str, version: str, bindings: dict) -> dict:
    from lfx.components.geo_workflow.scene_input import read_scene_index

    from terraflow.agentic.services.flow_run import run_working_flow

    stack = _call_stack.get()
    if flow_id in stack or len(stack) >= MAX_NESTING:
        message = "recursive_flow_call"
        raise ValueError(message)
    async with session_scope() as session:
        flow = await _owned(session, flow_id, user_id)
        data = copy.deepcopy(flow.data or {})
        meta = data.get(META) or {}
        if meta.get("state") != "active" or meta.get("version") != version:
            message = "unpublished_or_version_mismatch"
            raise ValueError(message)
        if not snapshot_valid(data):
            message = "snapshot_changed"
            raise ValueError(message)
    invocation_id = str(uuid4())
    bound = bind_inputs(data, meta["inputs"], bindings, read_scene_index(), invocation_id)
    token = _call_stack.set((*stack, flow_id))
    try:
        result = await run_working_flow(
            flow_data={"name": meta["name"], "data": bound}, flow_id=flow_id, user_id=user_id
        )
    finally:
        _call_stack.reset(token)
    records = result.get("vertex_results") or []
    rows = node_outputs(records)
    merged = {}
    for row in rows:
        merged.update(row["outputs"])
    return {
        "success": successful_run(result),
        "flow_id": flow_id,
        "version": version,
        "bindings": bindings,
        "outputs": merged,
        "results": rows,
        "evidence": {
            "invocation_id": invocation_id,
            "run_ids": sorted({r["run_id"] for r in records if r.get("run_id")}),
            "metrics": result.get("metrics"),
            "vertex_results": records,
        },
        "error": result.get("error"),
    }
