"""Read-only SceneInput explanation from actual index metadata and build records."""
from __future__ import annotations

import json
import re
from uuid import UUID

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
    """Use the existing owner-filtered history query; never execute a node."""
    if not flow_id or not user_id:
        return []
    try:
        from terraflow.services.deps import session_scope
        from terraflow.services.database.models.vertex_builds.crud import get_vertex_builds_by_flow_id

        async with session_scope() as session:
            rows = await get_vertex_builds_by_flow_id(session, UUID(flow_id), user_id=UUID(user_id))
        return [row.model_dump(mode="json") for row in rows]
    except (ValueError, TypeError):
        return []


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
        own = [b for b in builds if b.get("id") == node_id]
        output_records = [b for b in own if (b.get("data") or b.get("artifacts")) and b.get("valid") is True]
        fact = {"node_id": node_id, "scene_id": scene_id, "metadata": declared,
                "synthetic_from_explicit_metadata": synthetic, "metadata_found": bool(meta),
                "provenance_conflict": conflict,
                "own_successful_build_records": len(output_records),
                "own_builds": [{k: b.get(k) for k in ("id", "timestamp", "valid", "data", "artifacts")} for b in own],
                "has_downstream_edge": any(e.get("source") == node_id for e in data.get("edges", []))}
        facts.append(fact)
        status = "来源元数据相互冲突，暂不能判定真实/合成" if conflict else "元数据明确标注合成" if synthetic is True else "元数据标注观测来源（未独立验证传感器真实性）" if synthetic is False else "元数据未充分标明真实/合成来源，不能从路径名判断"
        lines.append(f"- 节点 {json.dumps(node_id, ensure_ascii=False)}，场景 {json.dumps(scene_id, ensure_ascii=False)}：{status}；"
                     f"已有自身成功执行记录 {len(output_records)} 条。")
    lines.append("无下游连接不等于没有节点自身输出。已记录输出与当前配置、索引元数据分别解释；未知来源保持未知。")
    if history_error:
        lines.append("本次历史记录读取失败，不能据此认定节点从未输出。")
    return {"result": "\n".join(lines), "task_success": not history_error,
            "analysis_performed": False, "scene_evidence": facts,
            "delivery_contract": {"version": VERSION, "kind": "scene_inspection"}}
