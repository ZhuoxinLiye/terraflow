"""Static wiring checks for Terrabox water flows the assistant builds.

The flow-run verification only catches errors that raise. A mis-wired water
flow usually runs: a threshold step fed with another step's mask, or a
two-date comparison whose "before" mask comes from the after scene, produces
a plausible number (or a gate refusal) instead of an exception. These checks
read the wiring alone (no run, no model) and return messages the agent can
act on; the verification loop feeds them back as fixable errors.
"""

from __future__ import annotations

from typing import Any

THRESHOLD = "TerraboxGeoRasterThresholdSegmentation"
EVIDENCE = "TerraboxGeoWaterWaterEvidence"
PAIR_INPUT = "WaterInputSet"
FIELD = "ToolResultField"
DATES = 2  # before and after
BY_CLASS = "TerraboxGeoWaterWaterByClass"
ALIGN = "TerraboxGeoWaterAlignRaster"
PREFLIGHT = "TerraboxGeoWaterRasterProfilePreflight"
COMPARE = "TerraboxGeoWaterCompareWithReference"


def _value(flow: dict, node_id: str, field: str) -> Any:
    for node in (flow.get("data") or {}).get("nodes") or []:
        if node.get("id") == node_id:
            return ((node.get("data") or {}).get("node", {}).get("template", {}).get(field) or {}).get("value")
    return None


def _nodes(flow: dict[str, Any]) -> dict[str, str]:
    """Node id -> component type."""
    out = {}
    for node in (flow.get("data") or {}).get("nodes") or []:
        if isinstance(node, dict) and node.get("id"):
            out[node["id"]] = (node.get("data") or {}).get("type") or ""
    return out


def _inputs(flow: dict[str, Any]) -> dict[tuple[str, str], tuple[str, str]]:
    """(target id, field) -> (source id, source output name)."""
    out = {}
    for edge in (flow.get("data") or {}).get("edges") or []:
        data = (edge or {}).get("data") or {}
        source, target = data.get("sourceHandle") or {}, data.get("targetHandle") or {}
        if source.get("id") and target.get("id") and target.get("fieldName"):
            out[(target["id"], target["fieldName"])] = (source["id"], source.get("name") or "")
    return out


def _origin(node_id: str, field: str, types: dict[str, str], inputs: dict) -> tuple[str, str] | None:
    """The component that really produces a value: skips ToolResultField hops."""
    seen = set()
    link = inputs.get((node_id, field))
    while link and link[0] not in seen:
        seen.add(link[0])
        if types.get(link[0]) != FIELD:
            return link
        link = inputs.get((link[0], "result"))
    return None


def geo_wiring_errors(flow: dict[str, Any]) -> list[str]:
    """Wiring mistakes in a Terrabox water flow; empty when none are found."""
    types, inputs = _nodes(flow), _inputs(flow)
    errors: list[str] = []
    raster_source: dict[str, tuple[str, str] | None] = {}
    for node_id, ctype in types.items():
        if ctype != THRESHOLD:
            continue
        source = _origin(node_id, "input_path", types, inputs)
        raster_source[node_id] = source
        if source and types.get(source[0]) == THRESHOLD:
            errors.append(
                f"{node_id}: input_path comes from the mask written by {source[0]}. Threshold the "
                "original raster instead (SceneInput `path`, or WaterInputSet `before_path` / `after_path`)."
            )

    if any(ctype == PAIR_INPUT for ctype in types.values()):
        pair_outputs = [s[1] for s in raster_source.values() if s and types.get(s[0]) == PAIR_INPUT]
        if len(pair_outputs) >= DATES and len(set(pair_outputs)) == 1:
            errors.append(
                f"Every threshold step reads WaterInputSet `{pair_outputs[0]}`; the two dates need one step on "
                "`before_path` and one on `after_path`."
            )

    for node_id, ctype in types.items():
        if ctype != EVIDENCE:
            continue
        for field, expected in (("before_path", "before_path"), ("after_path", "after_path")):
            mask = _origin(node_id, field, types, inputs)
            if not mask or types.get(mask[0]) != THRESHOLD:
                continue
            source = raster_source.get(mask[0])
            if source and types.get(source[0]) == PAIR_INPUT and source[1] != expected:
                errors.append(
                    f"{node_id}: {field} is the mask of {mask[0]}, which thresholds WaterInputSet `{source[1]}`. "
                    f"Wire {field} to the mask made from `{expected}`."
                )
    # The impact contract is stricter than independent single-scene estimates.
    # A disconnected preflight and two independently adaptive masks can both
    # execute without an exception, yet fail this scientific task.
    for node_id, ctype in types.items():
        if ctype != BY_CLASS or not (inputs.get((node_id, "before_path")) or _value(flow, node_id, "before_path")):
            continue
        masks = [_origin(node_id, field, types, inputs) for field in ("before_path", "after_path")]
        if any(not mask or types.get(mask[0]) != THRESHOLD for mask in masks):
            errors.append(f"{node_id}: water impact requires before_path and after_path from threshold masks.")
            continue
        before, after = (mask[0] for mask in masks)
        settings = ("input_transform", "direction", "foreground_value", "background_value", "nodata_value")
        if any(_value(flow, before, field) != _value(flow, after, field) for field in settings):
            errors.append(f"{node_id}: both masks need identical transform, direction and label semantics.")
        gates = [_origin(mask, "preconditions", types, inputs) for mask in (before, after)]
        if not gates[0] or gates[0] != gates[1] or types.get(gates[0][0]) != PREFLIGHT:
            errors.append(
                f"{node_id}: connect the SAME RasterProfilePreflight.api_run_model to BOTH masks.preconditions; "
                "a side branch is not a gate."
            )
        else:
            for mask, field in ((before, "before_path"), (after, "after_path")):
                if raster_source.get(mask) != _origin(gates[0][0], field, types, inputs):
                    errors.append(f"{node_id}: preflight {field} must inspect the original raster used by {mask}.")
        linked = inputs.get((before, "threshold"))
        shared_after = (
            linked
            and types.get(linked[0]) == FIELD
            and _value(flow, linked[0], "field_path") == "outputs.threshold"
            and _origin(before, "threshold", types, inputs) == (after, "api_run_model")
            and _value(flow, before, "method") == "fixed"
        )
        fixed_values = [_value(flow, mask, "threshold") for mask in (before, after)]
        shared_fixed = (
            all(_value(flow, mask, "method") == "fixed" for mask in (before, after))
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in fixed_values)
            and fixed_values[0] == fixed_values[1]
        )
        if not (shared_after or shared_fixed):
            errors.append(
                f"{node_id}: use one shared threshold: after result -> ToolResultField(outputs.threshold) -> "
                "before.threshold with before.method=fixed."
            )
        aligned = _origin(node_id, "class_path", types, inputs)
        if not aligned or types.get(aligned[0]) != ALIGN:
            errors.append(f"{node_id}: class_path must come from AlignRaster (nearest) on the original after grid.")
        elif _origin(aligned[0], "target_path", types, inputs) != raster_source.get(after):
            errors.append(f"{node_id}: AlignRaster.target_path must use the original after raster grid.")
        for compare_id, compare_type in types.items():
            if compare_type == COMPARE and _origin(compare_id, "predicted_path", types, inputs) != (
                after,
                "api_run_model",
            ):
                errors.append(f"{compare_id}: predicted_path must use the SAME after mask used by {node_id}.")
    return errors
