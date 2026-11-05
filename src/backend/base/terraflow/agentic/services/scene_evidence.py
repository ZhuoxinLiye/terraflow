"""Read-only SceneInput explanation from actual index metadata and build records."""
from __future__ import annotations

import json
import re
from uuid import UUID, uuid5

VERSION = "earthmind-scene-evidence-v1"


def scene_inspection_requested(text: str, user_history: list[str] | None = None) -> bool:
    subject = text
    if len(text) < 90 and re.search(r"^(那|这|它|刚才|上次|为什么|which|what about)", text, re.I):
        subject += "\n" + (user_history or [""])[-1]
    # A prohibition such as "不要修改或重新运行" requests read-only inspection.
    positive_actions = "。".join(part for part in re.split(r"[。；;\n]", text)
                                if not re.search(r"不要|不得|禁止|不运行|不执行|不修改|do not|don't|without", part, re.I))
    return bool(re.search(r"SceneInput|scene input|场景|数据|影像|节点", subject, re.I)
                and re.search(r"来源|合成|真实|输出|元数据|synthetic|provenance|metadata|output|无.*连接|没.*连|没有.*边", text, re.I)
                and not re.search(r"(?:请|现在|直接)(?:运行|执行)|重新运行|\brun\b|\bexecute\b", positive_actions, re.I))


async def load_scene_builds(flow_id: str | None, user_id: str | None) -> list[dict]:
    """Read owner-filtered vertex and native Trace histories; never run nodes.

    Workbench runs persist native spans even when vertex_builds is empty.
    Span/node association is resolved later from the native deterministic ID,
    never from a display name or another node selecting the same scene.
    """
    if not flow_id or not user_id:
        return []
    try:
        from terraflow.services.deps import session_scope
        from terraflow.services.database.models.vertex_builds.crud import get_vertex_builds_by_flow_id
        from terraflow.services.database.models.flow.model import Flow
        from terraflow.services.database.models.traces.model import SpanTable, TraceTable
        from sqlmodel import col, select

        async with session_scope() as session:
            rows = await get_vertex_builds_by_flow_id(session, UUID(flow_id), user_id=UUID(user_id))
            statement = (select(SpanTable, TraceTable)
                         .join(TraceTable, col(SpanTable.trace_id) == col(TraceTable.id))
                         .join(Flow, col(TraceTable.flow_id) == col(Flow.id))
                         .where(col(TraceTable.flow_id) == UUID(flow_id))
                         .where(col(Flow.user_id) == UUID(user_id))
                         .order_by(col(SpanTable.start_time)))
            spans = (await session.exec(statement)).all()
        return [row.model_dump(mode="json") for row in rows] + [
            {"evidence_source": "native_trace_span", "id": str(span.id), "trace_id": str(trace.id),
             "flow_id": str(trace.flow_id), "trace_status": trace.status.value,
             "status": span.status.value, "timestamp": span.start_time.isoformat(),
             "end_time": span.end_time.isoformat() if span.end_time else None,
             "inputs": span.inputs, "outputs": span.outputs, "error": span.error}
            for span, trace in spans
        ]
    except (ValueError, TypeError):
        return []


def _span_belongs_to_node(span: dict, node_id: str, flow_id: str | None) -> bool:
    """Exact inverse lookup of the ID convention used by NativeTracer."""
    from terraflow.services.tracing.span_sorting import TERRAFLOW_SPAN_NAMESPACE

    if span.get("evidence_source") != "native_trace_span" or (flow_id and span.get("flow_id") != flow_id):
        return False
    try:
        trace_id = UUID(span["trace_id"])
        try:
            expected = UUID(node_id)
        except (ValueError, TypeError):
            expected = uuid5(TERRAFLOW_SPAN_NAMESPACE, f"{trace_id}-{node_id}")
        return UUID(span["id"]) == expected
    except (KeyError, ValueError, TypeError):
        return False


def render_scene_evidence(flow: dict, index: dict, builds: list[dict], *, history_error: bool = False) -> dict | None:
    data = flow.get("data") or {}
    nodes = [n for n in data.get("nodes", []) if n.get("data", {}).get("type") == "SceneInput"]
    if not nodes:
        return None
    facts = []
    lines = ["以下只读检查当前画布配置、场景索引元数据与已有节点执行记录；没有运行流程。"]
    for node in nodes:
        node_id = node.get("id") or node.get("data", {}).get("id")
        template = node.get("data", {}).get("node", {}).get("template") or {}
        scene_id = template.get("scene_id", {}).get("value")
        meta = index.get(scene_id) or {}
        # Free-form descriptions/paths are never classified as provenance.
        declared = {k: meta[k] for k in ("input_kind", "origin", "sensor", "datetime", "source", "category") if k in meta}
        kind = str(meta.get("input_kind", "")).lower()
        origin = str(meta.get("origin", "")).lower()
        category = str(meta.get("category", "")).lower()
        declarations = {value for value in (kind, origin, category) if value in {"synthetic", "observed"}}
        conflict = declarations == {"synthetic", "observed"}
        synthetic = None if conflict else True if "synthetic" in declarations else False if "observed" in declarations else None
        own = [b for b in builds if b.get("evidence_source") != "native_trace_span" and b.get("id") == node_id]
        output_records = [b for b in own if (b.get("data") or b.get("artifacts")) and b.get("valid") is True]
        own_traces = [b for b in builds if _span_belongs_to_node(b, node_id, flow.get("id"))]
        trace_outputs = [b for b in own_traces if b.get("status") == "ok" and not b.get("error") and b.get("end_time")
                         and isinstance(b.get("outputs"), dict) and b["outputs"]]
        def output_scene(trace):
            metadata = trace["outputs"].get("metadata") or {}
            return (metadata.get("data") or metadata).get("scene_id") if isinstance(metadata, dict) else None

        current_scene_traces = [b for b in trace_outputs if (b.get("inputs") or {}).get("scene_id") == scene_id
                                and output_scene(b) == scene_id]
        fact = {"node_id": node_id, "scene_id": scene_id, "metadata": declared,
                "synthetic_from_explicit_metadata": synthetic, "metadata_found": bool(meta),
                "provenance_conflict": conflict,
                "own_successful_build_records": len(output_records),
                "own_builds": [{k: b.get(k) for k in ("id", "timestamp", "valid", "data", "artifacts")} for b in own],
                "own_successful_trace_records": len(trace_outputs), "own_traces": own_traces,
                "own_successful_output_evidence_records": len(output_records) + len(trace_outputs),
                "current_scene_successful_trace_records": len(current_scene_traces),
                "has_downstream_edge": any(e.get("source") == node_id for e in data.get("edges", []))}
        facts.append(fact)
        status = "来源元数据相互冲突，暂不能判定真实/合成" if conflict else "元数据明确标注合成" if synthetic is True else "元数据标注观测来源（未独立验证传感器真实性）" if synthetic is False else "元数据未充分标明真实/合成来源，不能从路径名判断"
        lines.append(f"- 节点 {json.dumps(node_id, ensure_ascii=False)}，场景 {json.dumps(scene_id, ensure_ascii=False)}：{status}；"
                     f"已有自身成功执行记录 {len(output_records) + len(trace_outputs)} 条"
                     f"（节点构建 {len(output_records)}、Trace输出 {len(trace_outputs)}）。")
        for trace in trace_outputs:
            executed_scene = (trace.get("inputs") or {}).get("scene_id")
            recorded_output_scene = output_scene(trace)
            ports = ", ".join(json.dumps(key, ensure_ascii=False) for key in trace["outputs"])
            lines.append(f"  Trace {trace['trace_id']} / span {trace['id']} 已记录该节点输出端口 {ports}；"
                         f"执行时 scene_id={json.dumps(executed_scene, ensure_ascii=False)}。")
            if executed_scene != scene_id or recorded_output_scene != scene_id:
                lines.append("  历史输入/输出场景与当前选择不同或记录不足，不能据此认定当前选择已经执行。")
        if not output_records and not trace_outputs:
            lines.append("  当前查询未找到该节点的成功输出记录；不等于该节点从未执行。")
    lines.append("无下游连接不等于没有节点自身输出。已记录输出与当前配置、索引元数据分别解释；未知来源保持未知。")
    lines.append("节点构建与Trace是不同记录来源，可能描述同次执行；记录条数不代表独立实验数。")
    if history_error:
        lines.append("本次历史记录读取失败，不能据此认定节点从未输出。")
    return {"result": "\n".join(lines), "task_success": not history_error,
            "analysis_performed": False, "scene_evidence": facts,
            "delivery_contract": {"version": VERSION, "kind": "scene_inspection"}}
