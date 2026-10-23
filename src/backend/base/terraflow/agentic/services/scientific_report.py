"""Evidence-bound delivery for the supported paired-water analysis.

The planner still chooses inputs, builds and runs the graph. This renderer
does not invent a graph or measurements, and never certifies arbitrary prose.
The original model response is retained separately from the delivered report.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def input_evidence(flow_data: dict, records: list[dict], rows: list[dict]) -> list[dict]:
    """Resolve actual executed input paths to local fixture/STAC declarations.

    No network lookup. A declared checksum is checked against the consumed
    file; metadata remains a declaration, not independent sensor validation.
    """
    used = {r["id"] for r in records}
    paths = set()
    for row in rows:
        out = row["outputs"]
        for key in ("source_ids", "source_id", "target_id"):
            paths.update(s for s in _strings(out.get(key)) if s.startswith("/"))
    for node in (flow_data.get("data") or {}).get("nodes", []):
        if node.get("id") not in used:
            continue
        template = node.get("data", {}).get("node", {}).get("template", {})
        paths.update(s for s in _strings(template) if s.startswith("/") and Path(s).is_file())
        if node.get("data", {}).get("type") == "WaterInputSet":
            from lfx.components.geo_workflow.water_input_set import list_input_sets

            directory = list_input_sets().get(template.get("input_set", {}).get("value"))
            if directory:
                paths.update(str(directory / f"{role}.tif") for role in ("before", "after"))
        if node.get("data", {}).get("type") == "SceneInput":
            from lfx.components.geo_workflow.scene_input import read_scene_index

            scene = read_scene_index().get(template.get("scene_id", {}).get("value"), {})
            if scene.get("path"):
                paths.add(scene["path"])

    roots = {Path(os.environ["TERRAFLOW_WATER_RUNTIME_DIR"])} if os.getenv("TERRAFLOW_WATER_RUNTIME_DIR") else set()
    for value in paths:
        roots.update(p for p in Path(value).parents if (p / "catalog").is_dir())
    catalog = {}
    for root in sorted(roots):
        for item in sorted((root / "catalog").glob("collections/*/items/*.json")):
            try:
                data = json.loads(item.read_text())
            except (OSError, ValueError):
                continue
            for asset in data.get("assets", {}).values():
                href = asset.get("href", "")
                local = Path(href) if href.startswith("/") else item.parent / href
                catalog[str(local.resolve())] = (item, data, asset)
    sources = []
    for value in sorted(paths):
        path = Path(value)
        if not path.is_file() or path.suffix.lower() not in {".tif", ".tiff", ".gpkg"}:
            continue
        fixture = path.parent / "fixture.json"
        meta = None
        if fixture.is_file() and path.stem in {"before", "after"}:
            try:
                data = json.loads(fixture.read_text())
                scene = data.get("scenes", {}).get(path.stem)
                if scene:
                    meta = {
                        "path": value,
                        "role": path.stem,
                        "metadata_file": str(fixture),
                        "signal_definition": data.get("type"),
                        "polarization": scene.get("polarization"),
                        "input_kind": data.get("input_kind"),
                        "input_scale": data.get("input_scale"),
                        "source": data.get("source"),
                        "license": data.get("license"),
                        "datetime": scene.get("datetime"),
                        "item_id": scene.get("item_id"),
                        "source_urls": [scene.get("stac_item_url") or scene.get("asset_href")],
                        "processing": data.get("grid", {}).get("resampling"),
                    }
            except (OSError, ValueError):
                pass
        match = catalog.get(str(path.resolve()))
        if match:
            item, data, asset = match
            props = data.get("properties", {})
            meta = {
                "path": value,
                "metadata_file": str(item),
                "item_id": data.get("id"),
                "role": props.get("workspace:data_type"),
                "origin": props.get("workspace:origin"),
                "datetime": props.get("datetime"),
                "license": props.get("license"),
                "description": props.get("description") or props.get("label:description"),
                "processing": props.get("processing:lineage"),
                "source_urls": [link["href"] for link in data.get("links", []) if link.get("rel") == "derived_from"],
                "declared_checksum": asset.get("file:checksum"),
                "class_table": asset.get("classification:classes"),
            }
        if meta:
            if match:
                try:
                    meta["collection_license"] = json.loads(
                        (match[0].parent.parent / "collection.json").read_text()
                    ).get("license")
                except (OSError, ValueError):
                    meta["collection_license"] = None
            hasher = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(chunk)
            digest = hasher.hexdigest()
            declared = meta.get("declared_checksum")
            meta.update(
                sha256=digest,
                checksum_matches=(declared in {digest, "1220" + digest}) if declared else None,
                evidence_depth="local_file_hash_and_metadata_declaration",
            )
            sources.append(meta)
    return sources


def report_facts(evidence: dict) -> tuple[dict, list[str]]:
    """Require one complete successful chain and check its arithmetic support."""
    rows = evidence.get("node_results", [])

    def one(key):
        matches = [r["outputs"] for r in rows if key in r["outputs"]]
        return matches[0] if len(matches) == 1 else None

    facts = {
        "change": one("change_answerable"),
        "classes": one("class_answerable"),
        "reference": one("comparison_answerable"),
        "rasterization": one("coverage_bbox_wgs84"),
    }
    errors = []
    if not facts["classes"] and not facts["reference"]:
        return {}, []  # unsupported graph: keep normal delivery
    if not all(facts.values()):
        return facts, ["incomplete_water_analysis"]
    if any(
        r.get("success") is False
        or r["outputs"].get("success") is False
        or r["outputs"].get("passed") is False
        or r["outputs"].get("execution_blocked")
        for r in rows
    ):
        errors.append("scientific_execution_failed")
    for key in ("change", "classes", "reference"):
        out = facts[key]
        if not out.get(
            {"change": "change_answerable", "classes": "class_answerable", "reference": "comparison_answerable"}[key]
        ):
            errors.append(f"{key}_not_answerable")
        if out.get("valid_pixels", 0) <= 0 or not out.get("area_method"):
            errors.append(f"{key}_missing_support")
        if not math.isclose(
            out.get("valid_area_m2", -1), out.get("valid_pixels", 0) * out.get("pixel_area_m2", 0), abs_tol=0.01
        ):
            errors.append(f"{key}_area_support_mismatch")
    c, cls, ref = (facts[k] for k in ("change", "classes", "reference"))
    checks = [
        (c["after_water_area_m2"] - c["before_water_area_m2"], c["net_water_change_m2"]),
        (c["new_water_area_m2"] - c["receded_water_area_m2"], c["net_water_change_m2"]),
        (sum(r["new_water_area_m2"] for r in cls["classes"]), cls["total_new_water_area_m2"]),
        (sum(r["class_area_m2"] for r in cls["classes"]), cls["valid_area_m2"]),
        (ref["agreement_area_m2"] + ref["predicted_only_area_m2"], ref["predicted_water_area_m2"]),
        (ref["agreement_area_m2"] + ref["reference_only_area_m2"], ref["reference_water_area_m2"]),
        (ref["predicted_water_area_m2"] - ref["reference_water_area_m2"], ref["area_difference_m2"]),
    ]
    for row in cls["classes"]:
        checks.extend(
            [
                (row["new_water_fraction_of_class"] * row["class_area_m2"], row["new_water_area_m2"]),
                (row["share_of_new_water"] * cls["total_new_water_area_m2"], row["new_water_area_m2"]),
            ]
        )
    if any(not math.isclose(a, b, abs_tol=0.01) for a, b in checks):
        errors.append("measurement_or_denominator_mismatch")
    sources = evidence.get("sources", [])
    sar_sources = [s for s in sources if s.get("role") in {"before", "after"}]
    if any(not s.get("input_scale") for s in sar_sources):
        errors.append("missing_input_scale")
    if not {"before", "after", "classification", "vector"}.issubset({s.get("role") for s in sources}):
        errors.append("missing_input_provenance")
    if any(
        not s.get("datetime")
        or not s.get("source_urls")
        or not all(s["source_urls"])
        or s.get("checksum_matches") is False
        for s in sources
    ):
        errors.append("incomplete_or_mismatched_source")
    thresholds = [r["outputs"] for r in rows if "threshold" in r["outputs"]]
    if (
        len(thresholds) != 2
        or len({(t["threshold"], t.get("input_transform"), t.get("direction")) for t in thresholds}) != 1
    ):
        errors.append("thresholds_not_shared")
    facts["profiles"] = one("common_valid_pixels")
    facts["alignment"] = one("resampling")
    if not facts["profiles"] or not facts["alignment"] or facts["alignment"].get("resampling") != "nearest":
        errors.append("missing_profile_or_categorical_alignment")
    facts["thresholds"] = thresholds
    return facts, errors


def constrained_delivery(data: dict, run: dict, *, duration: float, usage: dict) -> dict:
    """Deliver a computed report; retain raw prose without claiming to audit all NLP."""
    evidence = run.get("report_evidence") or {}
    try:
        facts, errors = report_facts(evidence)
    except (KeyError, TypeError, ValueError):
        facts, errors = {"unsupported_schema": True}, ["invalid_measurement_schema"]
    if not facts:
        return data
    audit = {
        "mode": "evidence_bound_renderer",
        "passed": not errors,
        "errors": errors,
        "raw_prose_certified": False,
        "model_response_replaced": True,
        "scientific_accuracy_validated": False,
        "release_ready": False,
    }
    raw = data.get("result", "")
    if errors:
        text = "本次执行的科学交付核验未通过：" + ", ".join(errors) + "。请检查原生节点证据；暂不交付统计结论。"
    else:
        c, cls, ref = (facts[k] for k in ("change", "classes", "reference"))

        def area(value):
            return f"{value / 1e6:.4f}"

        lines = ["已完成执行。以下报告由实际输入证据与工具结果生成，模型原始叙述另行保留。", "", "数据依据："]
        for source in evidence["sources"]:
            lines.append(
                f"- {source['role']}：{source.get('source') or source.get('item_id')}；时间 {source['datetime']}；"
                f"输入标度 {source.get('input_scale', '见产品说明')}；"
                f"信号 {source.get('signal_definition', '见产品说明')} / {source.get('polarization', '见产品说明')}；"
                f"item/fixture 许可 {source.get('license')}；"
                f"collection 许可 {source.get('collection_license', '未提供')}。"
                + " ".join(source["source_urls"])
            )
            if source.get("description"):
                lines.append("  " + source["description"])
            if source.get("processing"):
                lines.append("  处理：" + source["processing"])
        threshold = facts["thresholds"][0]
        lines += [
            "",
            f"两期采用相同阈值 {threshold['threshold']} "
            f"{'dB' if threshold.get('input_transform') == 'db' else '（原输入标度）'}，"
            f"工具输入变换 {threshold.get('input_transform')}；"
            "db 表示工具将线性功率转为 dB 后应用阈值，不能把线性输入写成 dB。",
            f"共同有效区 {c['valid_pixels']} 像元 / {area(c['valid_area_m2'])} km²；"
            f"排除 {c['excluded_pixels']} 像元；CRS {c['crs']}；网格 {c['grid_id']}；"
            f"像元 {c['pixel_area_m2']} m²；面积方法 {c['area_method']}。",
            f"栅格形状 {c['shape']}，仿射变换 {c['transform']}；原输入 nodata "
            f"before={facts['profiles']['before']['nodata']}、after={facts['profiles']['after']['nodata']}；"
            f"掩膜标签 {threshold.get('label_values')}。分类源 nodata={facts['alignment'].get('source_nodata')}、"
            f"对齐后 nodata={facts['alignment'].get('output_nodata')}。",
            f"前期水体 {area(c['before_water_area_m2'])}、后期 {area(c['after_water_area_m2'])}、"
            f"新增 {area(c['new_water_area_m2'])}、消失 {area(c['receded_water_area_m2'])}、"
            f"净增 {area(c['net_water_change_m2'])} km²。",
            "",
            f"分类共同有效区 {cls['valid_pixels']} 像元 / {area(cls['valid_area_m2'])} km²，"
            f"排除 {cls['excluded_pixels']} 像元；分类支持区新增合计 {area(cls['total_new_water_area_m2'])} km²。",
            "分类栅格按最近邻对齐，nodata 与任一输入无效像元排除。各占比只使用分类共同有效区。",
            "",
            "|类别|类别面积 km²|后期水体 km²|新增 km²|新增/类别 %|新增/全部新增 %|后期水体/类别 %|",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for row in cls["classes"]:
            lines.append(
                f"|{row['name']} ({row['value']})|{area(row['class_area_m2'])}|{area(row['water_area_m2'])}|"
                f"{area(row['new_water_area_m2'])}|{100 * row['new_water_fraction_of_class']:.4f}|"
                f"{100 * row['share_of_new_water']:.4f}|{100 * row['water_area_m2'] / row['class_area_m2']:.4f}|"
            )
        largest = max(cls["classes"], key=lambda r: r["new_water_area_m2"])
        lines += [
            "",
            f"新增最大类别为 {largest['name']}，{area(largest['new_water_area_m2'])} km²；"
            f"占分类区全部新增 {100 * largest['share_of_new_water']:.4f}%。",
            f"参考比较共同有效区 {ref['valid_pixels']} 像元 / {area(ref['valid_area_m2'])} km²；"
            f"预测 {area(ref['predicted_water_area_m2'])}、参考 {area(ref['reference_water_area_m2'])}、"
            f"重合 {area(ref['agreement_area_m2'])}、仅预测 {area(ref['predicted_only_area_m2'])}、"
            f"仅参考 {area(ref['reference_only_area_m2'])}、预测减参考 {area(ref['area_difference_m2'])} km²。",
            "参考覆盖区为声明范围 "
            + str(facts["rasterization"]["coverage_bbox_wgs84"])
            + "；区外 nodata，面外不独立证明观测干燥。",
            "参考与后期观测的日期和方法须分别解释；以上仅为范围差异，不报告同日精度。"
            "阈值水体与土地覆盖均为估计产品，不能据此确立洪水因果、受灾损毁或泛化精度。",
            "",
            (
                "已实际提出复用保存建议，等待确认，尚未发布。"
                if run.get("reuse_proposal")
                else "本次没有生成复用保存卡，未保存或发布可复用流程。"
            ),
            f"科学图耗时 {run.get('metrics', {}).get('duration_seconds')} 秒，"
            f"图内模型 token {run.get('metrics', {}).get('total_tokens')}；"
            f"完整 Agent 请求截至报告生成 {duration:.3f} 秒（含规划与模型调用）。"
            f"Agent 模型 token（服务计量）{usage.get('total_tokens', 0)}。",
        ]
        text = "\n".join(lines)
    return {**data, "result": text, "raw_model_response": raw, "report_audit": audit, "report_evidence": evidence}
