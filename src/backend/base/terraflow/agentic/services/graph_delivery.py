"""Deterministic delivery of executed annotation-graph evidence.

No graph queries or model calls occur here. The caller must bind each trusted
node ID to a graph_query slug from verified executed component identity, never
from model prose or an arbitrary node's ID/display name. A trustworthy-looking
output is insufficient by itself. Synthetic tests are not scientific results.
"""
from __future__ import annotations

import json
import re
from typing import Any


SLUGS = frozenset({"graph_query.get_item", "graph_query.query_nodes", "graph_query.search_graph"})
_HISTORY = re.compile(r"刚才|上次|之前|历史|继续|重跑|再跑|该设施|这个设施|上述|previous|earlier|again", re.I)
_GRAPH = re.compile(r"图谱|graph_query|graph\s+(?:query|annotation)|get_item|query_nodes|search_graph", re.I)
_IDS = re.compile(r"(?<![A-Za-z0-9_-])(?:N\d+|S-[A-Za-z0-9-]+|D\d{6,}|IMAGE)(?![A-Za-z0-9_-])")
_HASH = re.compile(r"[0-9a-f]{64}")
_CATEGORIES = {"vehicle_or_equipment_area": r"车辆|装备", "aviation_area": r"航空|停机坪|机场",
               "building": r"建筑|办公楼|宿舍", "storage_or_industrial_area": r"堆场|工业|建材",
               "training_or_test_area": r"训练|测试场|靶场", "target": r"业务类别\s*(?:为|=|是)\s*target"}


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _provenance(out: dict) -> tuple[dict, str | None]:
    p = out.get("provenance")
    if not isinstance(p, dict):
        return {}, "missing_provenance"
    sha = p.get("snapshot_sha256")
    if not isinstance(sha, str) or not _HASH.fullmatch(sha) or p.get("snapshot_id") != "sha256:" + sha:
        return {}, "invalid_snapshot_provenance"
    if p.get("read_only") is not True or not isinstance(p.get("synthetic"), bool) or not p.get("dataset_id"):
        return {}, "invalid_source_provenance"
    kind = p.get("evidence_kind")
    if kind not in {"existing_annotation_records", "model_detection_candidates"} or p.get("source_format") != "graph_annotations_json":
        return {}, "not_annotation_graph_evidence"
    keys = ("dataset_id", "snapshot_id", "snapshot_sha256", "source_version", "synthetic", "read_only", "evidence_kind")
    safe = {k: p.get(k) for k in keys}
    if kind == "model_detection_candidates":
        image, detection = p.get("image"), p.get("detection_provenance")
        if (not isinstance(image, dict) or not isinstance(detection, dict)
                or not re.fullmatch(r"segearth:[a-f0-9]{32}", str(p["dataset_id"]))
                or p.get("source_version") != "segearth-detections-v1"
                or p.get("category_method") != "explicit_model_category"
                or not all(_integer(image.get(k)) and image[k] > 0 for k in ("width", "height"))
                or image.get("coordinate_system") != "original_image_pixels" or image.get("crs") is not None
                or not isinstance(image.get("sha256"), str) or not _HASH.fullmatch(image["sha256"])
                or detection.get("input_sha256") != image["sha256"] or detection.get("source_model") != "segearth"):
            return {}, "invalid_detection_provenance"
        safe.update(image=image, detection_provenance=detection)
    return safe, None


def _affirmative_operation(pattern: str, text: str) -> bool:
    for match in re.finditer(pattern, text, re.I):
        # A negated extra operation must not become a delivery requirement.
        # Scope negation to the current clause; a later explicit request still
        # counts (e.g. "不要搜索，但请读取详情").
        prefix = re.split(r"[。；;，,\n]|但是|但|然后|另外", text[:match.start()])[-1]
        if not re.search(r"无需|不要|不必", prefix):
            return True
    return False


def _requested(text: str) -> set[str]:
    ops = set()
    if _affirmative_operation(r"详情|父级|对象类型|item_type|get_item", text):
        ops.add("graph_query.get_item")
    if re.search(r"计数|多少|统计|总数|query_nodes|\bcount\b|全部(?:目标|target)", text, re.I):
        ops.add("graph_query.query_nodes")
    # Error/ambiguity outputs already include candidates; mentioning those
    # candidates does not request another search operation.
    if _affirmative_operation(r"查找|搜索|search_graph|matched_fields|lookup", text):
        ops.add("graph_query.search_graph")
    return ops


def _complete_current_query(text: str) -> bool:
    """An explicit current scoped query supplies its own delivery contract."""
    value = r"\s*[=:：]\s*[`\"']?[A-Za-z0-9][A-Za-z0-9_-]*"
    return ("graph_query.query_nodes" in _requested(text)
            and bool(re.search(r"\b(?:facility_id|partition_id)" + value, text))
            and bool(re.search(r"\b(?:node_type|target_type_contains)" + value, text)))


def _affirmative(text: str) -> str:
    # Contract reminders prohibiting a filter must never authorize that filter.
    return "。".join(part for part in re.split(r"[。；;\n]", text)
                    if not re.search(r"不得|不要|不能|禁止|不添加|未要求|leave .*absent|never add|do not", part, re.I))


def _tool_help_request(text: str) -> bool:
    help_topic = re.search(r"参数|字段|schema|元数据|metadata|用法|如何使用|怎么用|含义|什么意思", text, re.I)
    asks_result = re.search(r"多少|(?:报告|给出|告诉|返回|交付)[^。\n]{0,20}(?:计数|总数|结果|数量)|实际(?:调用|执行|运行)", text)
    history_result = _HISTORY.search(text) and re.search(r"结果|计数|总数|输出", text)
    specific_result = (_IDS.search(text) and re.search(r"结果|计数|总数|输出", text)) or re.search(r"(?:本次|此次|实际|当前)(?:的)?(?:计数|总数|结果|输出)", text)
    return bool(help_topic and not asks_result and not history_result and not specific_result)


def _query_parameter_help(data: dict, text: str) -> dict:
    """Finite help from the locally inspected graph adapter contract."""
    if not (re.search(r"query_nodes", text, re.I) and re.search(r"node_type|target_type_contains", text, re.I)):
        return data
    audit = {"kind": "annotation_graph_tool_contract", "passed": True,
             "tool": "graph_query.query_nodes", "adapter_version": "0.2.0",
             "contract_revision": "n077-query-nodes-2026-11-06", "annotation_baseline_commit": "3e49f1e",
             "source_files": ["terrabox:src/terrabox/toolkits/graph_query.py", "terrabox:src/terrabox/core/graph_query_data.py"],
             "evidence_kind": "locally_inspected_adapter_contract", "tool_execution_claimed": False}
    payload = dict(data)
    payload.setdefault("model_response_original", data.get("result"))
    payload.update(task_success=True, tool_contract_audit=audit, report_audit=audit,
        result=("graph_query.query_nodes 的两个筛选维度独立。\n"
                "node_type 是可选层级筛选，仅支持 facility 或 target；不支持 node_type=area。"
                "区域范围用 partition_id 指定精确 area ID，设施范围用 facility_id 指定精确设施 ID。"
                "node_type=target 包含该层级的所有业务类别。\n"
                "target_type_contains 是可选业务类别筛选，仅在明确要求类别时填写 allowed_target_types 中的一个完整类别码；"
                "当前适配器按相等匹配，字段名 contains 不表示可做子串匹配。未要求类别或风险时留空。\n"
                "limit 只截断返回列表，不改变完整 count。已有图谱的计数单位是标注记录；"
                "segearth: 数据集的计数单位是模型候选区域，类别使用 allowed_target_types 声明的模型类别。"
                "检测数据用 dataset_id 选择，并用 snapshot_id 固定快照；partition_id=IMAGE 表示整张检测影像。"
                "来源：本地 graph_query 适配契约 0.2.0，2026-11-06核对。"))
    return payload


def _allowed_category(text: str, category: str) -> bool:
    positive = _affirmative(text)
    explicit = re.search(r"target_type_contains\s*[=:：]\s*[`\"']?" + re.escape(category) + r"\b", positive)
    return bool(explicit or (category in _CATEGORIES and re.search(_CATEGORIES[category], positive, re.I)))


def _scope_errors(out: dict, text: str) -> list[str]:
    filters = out.get("filters_applied")
    if not isinstance(filters, dict):
        return ["missing_filters_applied"]
    errors = []
    category = filters.get("target_type_contains")
    if category is not None and (not isinstance(category, str) or not _allowed_category(text, category)):
        errors.append("unrequested_business_category")
    if "risk_level" in filters and not re.search(r"risk_level\s*[=:：]\s*[`\"']?unknown|风险.{0,6}(?:unknown|未知)", _affirmative(text), re.I):
        errors.append("unrequested_risk_filter")
    requested_ids = set(_IDS.findall(text))
    for key in ("facility_id", "partition_id"):
        if key in filters and requested_ids and filters[key] not in requested_ids:
            errors.append("unrequested_scope")
        explicit = re.findall(key + r"\s*[=:：]\s*[`\"']?([A-Za-z0-9-]+)", text)
        if explicit and filters.get(key) not in explicit:
            errors.append("scope_does_not_match_request")
    if re.search(r"(?:设施|facility)\s*[`\"']?N\d+|N\d+[^。\n]{0,10}设施", text, re.I) and not filters.get("facility_id"):
        errors.append("requested_facility_scope_missing")
    if re.search(r"(?:全部|所有|all)[^。\n]{0,16}(?:target|目标)", text, re.I) and filters.get("node_type") == "facility":
        errors.append("wrong_hierarchy_level")
    return errors


def _validated_row(row: dict, slug: str, text: str) -> tuple[dict, list[str]]:
    out = row.get("outputs")
    if not isinstance(out, dict):
        return {}, ["missing_tool_output"]
    p, err = _provenance(out)
    errors = [err] if err else []
    safe = {"tool": slug, "node_id": row.get("node_id"), "provenance": p}
    for key, pattern in (("dataset_id", r"segearth:[a-f0-9]{32}"), ("snapshot_id", r"sha256:[a-f0-9]{64}")):
        requested = set(re.findall(pattern, text))
        if requested and p.get(key) not in requested:
            errors.append("requested_" + key + "_mismatch")
    if row.get("success") is not True or out.get("success") is not True or out.get("ok") is not True or out.get("execution_blocked") is not False:
        safe["reason_code"] = str(out.get("reason_code") or "tool_execution_failed")
        error = out.get("error")
        if isinstance(error, dict) and isinstance(error.get("candidates"), list):
            safe["candidate_ids"] = [r.get("id") for r in error["candidates"] if isinstance(r, dict) and isinstance(r.get("id"), str)]
        return safe, errors + [safe["reason_code"]]
    expected_unit = "model_candidate_regions" if p.get("evidence_kind") == "model_detection_candidates" else "annotation_records"
    if out.get("count_unit") != expected_unit:
        errors.append("invalid_count_unit")
    safe["count_unit"] = expected_unit
    requested_ids = set(_IDS.findall(text))
    if slug == "graph_query.get_item":
        if not isinstance(out.get("item_id"), str) or out.get("item_type") not in {"area", "facility", "target"}:
            errors.append("invalid_item_identity")
        safe.update(item_id=out.get("item_id"), item_type=out.get("item_type"),
                    parent_ids=[r.get("id") for r in out.get("parents", []) if isinstance(r, dict)])
        if requested_ids and out.get("item_id") not in requested_ids:
            errors.append("unrequested_item")
        if "member_count" in out:
            if not _integer(out["member_count"]):
                errors.append("invalid_member_count")
            safe["member_count"] = out["member_count"]
    elif slug == "graph_query.query_nodes":
        count, returned, nodes, truncated = (out.get(k) for k in ("count", "returned_count", "nodes", "truncated"))
        if not (_integer(count) and _integer(returned) and isinstance(nodes, list) and returned == len(nodes)
                and returned <= count and isinstance(truncated, bool) and truncated == (count > returned)):
            errors.append("invalid_count_or_truncation")
        if out.get("count_semantics") != "total_matches_before_limit":
            errors.append("invalid_count_semantics")
        errors.extend(_scope_errors(out, text))
        limits = re.findall(r"\blimit\s*[=:：]\s*(\d+)", text, re.I)
        if limits and _integer(count) and _integer(returned) and returned != min(count, int(limits[-1])):
            errors.append("requested_limit_not_satisfied")
        for key in ("by_node_type", "by_target_type"):
            dist = out.get(key)
            if isinstance(dist, dict) and (any(not _integer(v) for v in dist.values()) or sum(dist.values()) != count):
                errors.append("invalid_distribution")
        safe.update(count=count, returned_count=returned, truncated=truncated,
                    example_ids=[r.get("id") for r in (nodes if isinstance(nodes, list) else []) if isinstance(r, dict)], filters_applied=out.get("filters_applied"))
    else:
        matches = out.get("matches")
        total, returned, count = (out.get(k) for k in ("total_matches", "returned_count", "count"))
        if not (_integer(total) and _integer(returned) and _integer(count) and isinstance(matches, list)
                and returned == count == len(matches) and total >= returned
                and isinstance(out.get("truncated"), bool) and out["truncated"] == (total > returned)):
            errors.append("invalid_search_count")
        if out.get("count_semantics") != "returned_candidates_not_node_population":
            errors.append("invalid_search_semantics")
        if requested_ids and out.get("query") not in requested_ids:
            errors.append("unrequested_search_query")
        if re.search(r"source_types[^。\n]{0,12}(?:只|仅|only)[^。\n]{0,8}node|source_types\s*=\s*\[?node", text, re.I) and out.get("source_types") != ["node"]:
            errors.append("unrequested_search_source")
        safe.update(total_matches=total, returned_count=returned, truncated=out.get("truncated"),
                    query=out.get("query"), source_types=out.get("source_types"),
                    matches=[{k: r.get(k) for k in ("id", "source_type", "matched_fields")} for r in (matches if isinstance(matches, list) else []) if isinstance(r, dict)])
    return safe, errors


def constrained_graph_delivery(data: dict, runs: list[dict], *, user_text: str,
                               recent_user_texts: list[str] | None = None,
                               prior_runs: list[dict] | None = None,
                               trusted_graph_nodes: dict[str, str] | None = None) -> dict:
    """Replace free-form graph numbers with validated actual execution evidence.

    History evidence is eligible only for an explicit history/follow-up request.
    Runs must be actual runner events, and trusted identity must be supplied by
    the caller after canonical component verification. On failure no count is
    delivered. This does not certify arbitrary requests outside this contract.
    """
    historical = bool(_HISTORY.search(user_text))
    if _tool_help_request(user_text):
        return _query_parameter_help(data, user_text)
    context = "\n".join([*(recent_user_texts or []), user_text]) if historical and not _complete_current_query(user_text) else user_text
    eligible = runs or (prior_runs or [] if historical else [])
    latest = eligible[-1] if eligible else {}
    evidence = latest.get("report_evidence", latest) if isinstance(latest, dict) else {}
    if not isinstance(evidence, dict):
        evidence = {}
    identities = trusted_graph_nodes if trusted_graph_nodes is not None else evidence.get("trusted_tool_nodes", {})
    trusted = {k: v for k, v in identities.items() if isinstance(k, str) and isinstance(v, str) and v in SLUGS} if isinstance(identities, dict) else {}
    if not _GRAPH.search(context) and not (trusted and eligible):
        return data
    payload = dict(data)
    payload.setdefault("model_response_original", data.get("result"))
    errors: list[str] = []
    safe_rows = []
    actual = set()
    if not eligible:
        errors.append("no_actual_graph_execution")
    else:
        rows = evidence.get("node_results", []) if isinstance(evidence, dict) else []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            slug = trusted.get(row.get("node_id")) if isinstance(row.get("node_id"), str) else None
            if slug is None:
                continue
            actual.add(slug)
            safe, failures = _validated_row(row, slug, context)
            safe_rows.append(safe)
            errors.extend(failures)
        if not safe_rows:
            errors.append("no_trusted_graph_tool_results")
    required = _requested(context)
    if required - actual:
        errors.append("requested_graph_operation_missing")
    if not required:
        errors.append("request_contract_not_resolved")
    snapshots = {(r["provenance"].get("snapshot_sha256"), r["provenance"].get("dataset_id"), r["provenance"].get("synthetic"))
                 for r in safe_rows if r.get("provenance")}
    if len(snapshots) > 1:
        errors.append("mixed_graph_snapshots")
    for query in (r for r in safe_rows if r.get("tool") == "graph_query.query_nodes"):
        filters = query.get("filters_applied") or {}
        if "target_type_contains" not in filters and "risk_level" not in filters and filters.get("node_type") in {None, "target"}:
            for detail in (r for r in safe_rows if r.get("tool") == "graph_query.get_item"):
                if detail.get("item_type") == "facility" and filters.get("facility_id") == detail.get("item_id") and query.get("count") != detail.get("member_count"):
                    errors.append("detail_and_query_count_disagree")
    errors = list(dict.fromkeys(errors))
    passed = not errors
    audit = {"kind": "annotation_graph", "passed": passed, "reason_codes": errors,
             "required_tools": sorted(required), "actual_tools": sorted(actual),
             "history_used": not bool(runs) and bool(eligible), "evidence": safe_rows}
    payload.update(graph_report_audit=audit, report_audit=audit, task_success=passed)
    if passed:
        detection = any(r["provenance"].get("evidence_kind") == "model_detection_candidates" for r in safe_rows)
        boundary = ("计数单位为模型候选区域，来自语义分割的连通区域，未经逐目标人工核验。"
                    "坐标和 area_px 使用原图像素；没有地理坐标系或平方米面积。原始 logit 不是校准置信度。"
                    if detection else
                    "计数单位为已有标注记录。这些记录不代表单个车辆数或影像新检测。")
        payload["result"] = ("只读图谱工具已实际执行，以下仅列本次工具支持的结果。\n\n"
                             + "\n\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in safe_rows)
                             + "\n\n" + boundary + "limit 只截断返回列表，不改变完整 count；合法零结果是成功查询。"
                               "结果不证明洪水成因、新增淹没或当前现场条件。"
                               "synthetic=true 的来源是合成测试数据。")
    else:
        candidates = sorted({c for r in safe_rows for c in r.get("candidate_ids", [])})
        payload["result"] = "本次图谱任务未完成：" + "、".join(errors) + "。未扩大查询范围，未将错误当作零结果或交付未核验计数。"
        if candidates:
            payload["result"] += "同名候选 ID：" + "、".join(candidates) + "；请指定 ID 或区域后再查询。"
    return payload
