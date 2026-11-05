"""Finite Earthmind scientific delivery contracts, not a general prose judge.

Only user-authored turns select a contract. Tool metadata and model prose never
select rules or provide replacement instructions. Actual executions remain the
agent's responsibility; these renderers do not build or execute a substitute graph.
"""
from __future__ import annotations

import copy
import math
import re
from collections import OrderedDict
from dataclasses import dataclass

VERSION = "earthmind-scientific-delivery-v1"
SUPPORTED_AREA_METHOD = "affine_pixel_area_with_projected_crs_unit_conversion"

CARDS = {
    "angular_area": (
        "经纬度网格的角度单位不能直接当作平方米。像元的平方米面积需要实际位置、"
        "像元边界和坐标参考信息，由适当投影或椭球大地测量工具计算。"
        "缺少这些输入时不选取假设纬度、不提供平方米示例；这里没有执行面积测量。"
    ),
    "water_inference": (
        "单时相水体掩膜是该时相水体范围的估计，不能单独认定新增淹没或洪水成因。"
        "变化分析需经核验的洪前或历史水范围等可比基准，并先检查时间、空间对齐、"
        "有效观测区域和传感器可比性。配对掩膜差分是当前支持的方法之一，不是唯一方法。"
        "水体变化仍不能独立确立洪水因果；降雨、放水、潮位等机制需结合事件证据评估，"
        "不能一律当作排除洪水的条件。这里没有执行检测、面积测量或因果核验。"
    ),
    "site_safety": (
        "面积、空间距离或看似空旷只能用于候选信息，不能认定安全起降或救援适用性。"
        "公园总面积不等于实际可用净空；空间距离不证明路径、可达性或接驳时间。"
        "需另行核查具体机型与适用运行规范、实际场地和障碍物、空域、气象及人员条件。"
        "这里不规定通用几何形状或尺寸标准，也未核实现场安全。"
        "图谱有哪些字段须查询实际返回，不能由面积或距离推定存在多边形或其他字段。"
    ),
    "missing_measurement": (
        "没有可核验的实际工具测量结果，不能交付本次面积、像元量或变化数值。"
        "请提供或选择要分析的数据、范围与时间；已有历史结果可通过对应记录核对。"
        "水体变化还需可比基准、有效观测区、空间对齐、CRS与面积计算方法。"
        "不能先报数再补证据；本回答没有执行测量。"
    ),
}


def _has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, re.I))


@dataclass(frozen=True)
class ScientificRequest:
    topic: str | None = None
    conceptual: bool = False
    historical: bool = False


def classify_scientific_request(text: str, user_history: list[str] | None = None) -> ScientificRequest:
    """Composable domain/act recognition; unknown operational tasks keep the agent.

    Context is limited to the most recent *user* subject for short anaphoric
    follow-ups. It does not concatenate every prior subject into a new request.
    File paths, IDs and data selections are never interpreted as missing data.
    """
    current = text.strip()
    topic_text = current
    anaphoric = _has(r"^(那|那么|这个|这|它|所以|刚才|上次|之前|继续|为什么|多少|能否|可以|what about|why|that|it\b|previous)", current)
    if len(current) < 100 and anaphoric and not _has(r"EPSG|经纬|水体|掩膜|直升|起降|landing|flood|water|latitude", current):
        topic_text += "\n" + next((t for t in reversed(user_history or []) if t.strip()), "")
    historical = _has(r"上次|刚才|此前|之前|历史结果|已保存.*结果|previous|last (?:run|result)|earlier", current) or (topic_text != current and anaphoric)
    angular = _has(r"EPSG\s*:?\s*4326|经纬度|平方度|degree|latitude|角度.*像元", topic_text)
    area = _has(r"面积|平方|平方米|m[²2]|area|pixel|像元", topic_text)
    safety = _has(r"直升机|起降|适航|helicopter|landing|救援.*安全|安全.*救援", topic_text)
    water = _has(r"水体|水掩膜|水.*分割|water|flood|淹没|洪水", topic_text)
    conceptual = _has(r"能否|是否|是不是|能不能|可不可以|可以|能.*吗|说明|解释|意味着|等于|认定|足以|依据|区别|直接|can\b|does\b|why|explain|mean|enough|sufficient", current)
    positive_actions = re.sub(r"(?:不要|不得|禁止|无需|不|别)(?:重新|再)?(?:计算|测量|估算|执行|运行|重跑)|\b(?:do not|don't|never)\s+(?:run|execute|calculate|measure)\b", "", current, flags=re.I)
    operation = _has(r"调用|执行|运行|查询|查找|检索|读取|列出|筛选|选择|计算|测量|估算|给出.*结果|run\b|execute|query|search|read\b|list\b|select|calculate|measure|estimate", positive_actions)
    code_or_flow_edit = _has(r"(?:创建|编写|修改|配置|生成|搭建).{0,20}(?:组件|代码|工作流|流程)|(?:create|write|edit|configure|build).{0,30}(?:component|code|workflow)", current)
    if code_or_flow_edit and not _has(r"执行|运行|\brun\b|execute", positive_actions):
        return ScientificRequest()
    no_input = _has(r"(?:没有|未|没)(?:提供|给|有|上传|选择).{0,20}(?:数据|影像|掩膜|路径|结果)|no (?:data|imagery|images|mask|measurement)|先报.{0,20}(?:补|证)|before.{0,20}evidence", current)
    topic = "site_safety" if safety else "angular_area" if angular and area else "water_inference" if water else None
    if topic is None:
        return ScientificRequest()
    # A conceptual question can explicitly forbid assumed/missing data without
    # requesting a measurement. A request to report first and verify later is
    # still a missing-evidence delivery, even when phrased as "可以吗".
    report_before_evidence = _has(r"先报.{0,20}(?:补|证)|before.{0,20}evidence", current)
    if conceptual and not operation and not report_before_evidence:
        return ScientificRequest(topic, True, historical)
    if no_input and not historical:
        return ScientificRequest("missing_measurement", True, False)
    measurement = _has(r"多少|计算|估算|测量|面积|平方米|像元|数值|calculate|measure|how (?:much|many)|area|pixels?", current)
    if topic in {"angular_area", "water_inference"} and measurement and (operation or not conceptual):
        return ScientificRequest("measurement", False, historical)
    if operation and not conceptual and not measurement and topic == "water_inference":
        return ScientificRequest()
    return ScientificRequest(topic, conceptual and not operation, historical)


def scientific_execution_forbidden(text: str) -> bool:
    """Explicit no-rerun requests also apply to short historical follow-ups."""
    return _has(r"(?:不|不要|不得|禁止|无需|别)(?:修改或)?(?:重新|再)?(?:执行|运行|重跑)|\b(?:do not|don't|never|without)\s+(?:re-?running|run|execute|rerun)\b", text)


def clarification(request: ScientificRequest, *, raw: str = "") -> dict:
    """Successful explanation is distinct from an unperformed measurement."""
    missing = request.topic == "missing_measurement"
    return {
        "result": CARDS[request.topic],
        "raw_model_response": raw,
        "task_success": not missing,
        "analysis_performed": False,
        "delivery_contract": {"version": VERSION, "kind": "missing_evidence" if missing else "clarification", "topic": request.topic},
        **({"reason_code": "measurement_evidence_required"} if missing else {}),
    }


def historical_measurement_request(text: str, request: ScientificRequest, runs: list[dict]) -> ScientificRequest:
    """Resolve anaphoric numbers from typed prior evidence, not model history."""
    if request.topic is not None or len(text) > 100:
        return request
    if not _has(r"刚才|上次|之前|那|这个|previous|last result|that", text) or not _has(r"多少|数值|面积|结果|how much|area|value", text):
        return request
    for run in runs:
        identities = (run.get("report_evidence") or {}).get("trusted_tool_nodes") or {}
        if any(slug in {"geo_water.water_evidence", "geo_water.water_extent"} for slug in identities.values()):
            return ScientificRequest("measurement", False, True)
    return request


# Same process/session lifetime and tenant boundary as conversation memory. Raw
# model text is never stored as evidence. Entries are copies of backend run events.
_runs: OrderedDict[tuple[str, str, str], list[dict]] = OrderedDict()


def remember_runs(user_id: str | None, session_id: str | None, flow_id: str | None, runs: list[dict]) -> None:
    if not user_id or not session_id or not flow_id or not runs:
        return
    key = (user_id, session_id, flow_id)
    _runs[key] = copy.deepcopy(runs[-1:])
    _runs.move_to_end(key)
    while len(_runs) > 100:
        _runs.popitem(last=False)


def previous_runs(user_id: str | None, session_id: str | None, flow_id: str | None) -> list[dict]:
    return copy.deepcopy(_runs.get((user_id, session_id, flow_id), [])) if user_id and session_id and flow_id else []


def clear_runs(user_id: str, session_id: str) -> None:
    for key in list(_runs):
        if key[:2] == (user_id, session_id):
            del _runs[key]


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def measurement_delivery(data: dict, runs: list[dict], *, historical: bool = False) -> dict:
    """Allowlisted renderer for actual water-change tool outputs, never raw prose.

    Existing full paired-water reports retain their stronger multi-chain audit.
    Here a lone supported change result needs successful execution, finite metric
    arithmetic, projected area support and recorded two-date input provenance.
    Other schemas fail with an honest unsupported-evidence result, not invented
    data absence. No natural-language number extraction or model-supplied proof.
    """
    raw = data.get("raw_model_response", data.get("result", ""))
    prefix = "上次已记录执行" if historical else "本次执行"
    required = ("valid_area_m2", "pixel_area_m2", "valid_pixels", "before_water_area_m2", "after_water_area_m2", "new_water_area_m2", "receded_water_area_m2", "net_water_change_m2")
    for run in reversed(runs[-1:]):
        evidence = run.get("report_evidence") or {}
        rows = evidence.get("node_results") or []
        for row in rows:
            out = row.get("outputs") or {}
            if evidence.get("trusted_tool_nodes", {}).get(row.get("node_id")) != "geo_water.water_evidence":
                continue
            if row.get("success") is False or out.get("success") is False or out.get("execution_blocked"):
                continue
            if out.get("change_answerable") is not True or not all(_finite(out.get(k)) for k in required):
                continue
            if out.get("area_method") != SUPPORTED_AREA_METHOD or not out.get("crs") or str(out["crs"]).upper() in {"EPSG:4326", "4326"}:
                continue
            if out["valid_pixels"] <= 0 or out["pixel_area_m2"] <= 0:
                continue
            if any(out[k] < 0 or out[k] > out["valid_area_m2"] for k in required if k.endswith("area_m2") and k != "valid_area_m2"):
                continue
            if not all((math.isclose(out["valid_area_m2"], out["valid_pixels"] * out["pixel_area_m2"], abs_tol=0.01),
                        math.isclose(out["after_water_area_m2"] - out["before_water_area_m2"], out["net_water_change_m2"], abs_tol=0.01),
                        math.isclose(out["new_water_area_m2"] - out["receded_water_area_m2"], out["net_water_change_m2"], abs_tol=0.01))):
                continue
            sources = evidence.get("sources") or []
            supported = [s for s in sources if s.get("role") in {"before", "after"} and s.get("datetime")
                         and isinstance(s.get("sha256"), str) and re.fullmatch(r"[0-9a-fA-F]{64}", s["sha256"])
                         and isinstance(s.get("source_urls"), list) and s["source_urls"] and all(isinstance(url, str) and url.strip() for url in s["source_urls"])
                         and s.get("checksum_matches") is not False]
            if {s["role"] for s in supported} != {"before", "after"}:
                continue
            # Require a server execution receipt associated with this exact node.
            receipts = []
            for record in run.get("vertex_results") or []:
                if record.get("id") != row.get("node_id"):
                    continue
                for artifact in (record.get("data", {}).get("artifacts") or {}).values():
                    result = artifact.get("raw") if isinstance(artifact, dict) else None
                    if isinstance(result, dict) and result.get("success") is True and result.get("outputs") == out and result.get("execution_id"):
                        receipts.append(str(result["execution_id"]))
            if not receipts:
                continue
            facts = {k: out[k] for k in required}
            text = (
                f"{prefix}的水体变化工具记录：新增水体估计 {out['new_water_area_m2']:g} 平方米；"
                f"退去水体估计 {out['receded_water_area_m2']:g} 平方米；净变化 {out['net_water_change_m2']:g} 平方米。\n"
                f"有效观测面积 {out['valid_area_m2']:g} 平方米；面积方法与CRS见所附执行证据。"
                "上述数值来自工具输出，是水体变化估计，不能单独认定新增洪灾、因果、损毁或人员安全。"
            )
            return {**data, "result": text, "raw_model_response": raw, "task_success": True, "analysis_performed": not historical,
                    "delivery_contract": {"version": VERSION, "kind": "tool_measurement", "historical": historical},
                    "measurement_evidence": {"execution_ids": receipts, "node_id": row["node_id"], "values": facts, "unit": "m2", "area_method": out["area_method"], "crs": out["crs"],
                                             "sources": [{k: s.get(k) for k in ("role", "datetime", "sha256", "source_urls")} for s in supported]}}
    message = (
        "已找到执行记录，但其中缺少本交付类型要求的成功测量、单位、面积支持或来源核验，暂不交付数值。"
        if runs else "当前没有可核验的实际工具测量记录，暂不交付数值。可继续选择数据并调用已有测量工具，或指定要核对的历史运行。"
    )
    return {**data, "result": message, "raw_model_response": raw, "task_success": False, "analysis_performed": False,
            "reason_code": "measurement_evidence_required", "delivery_contract": {"version": VERSION, "kind": "unsupported_measurement", "historical": historical}}


def constrain_scientific_delivery(data: dict, request: ScientificRequest, runs: list[dict]) -> dict:
    if request.topic is None:
        return data
    if request.topic == "measurement":
        return measurement_delivery(data, runs, historical=request.historical)
    # Tool tasks are still executed. Their numeric/field outputs remain in the
    # result cards; an inference of safety/causation is a separate bounded claim.
    bounded = clarification(request, raw=data.get("raw_model_response", data.get("result", "")))
    if data.get("graph_report_audit"):
        return {**data, "result": data.get("result", "") + "\n\n" + bounded["result"],
                "raw_model_response": data.get("model_response_original", bounded["raw_model_response"]),
                "scientific_delivery_contract": bounded["delivery_contract"]}
    return {**data, **bounded}
