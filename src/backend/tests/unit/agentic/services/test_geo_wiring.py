"""Static wiring checks for Terrabox water flows (synthetic flow dicts, no rasters)."""

from terraflow.agentic.services.flow_run_error_classification import RunErrorKind, classify_run_error
from terraflow.agentic.services.geo_wiring import geo_wiring_errors


def _flow(nodes, edges):
    return {
        "data": {
            "nodes": [{"id": i, "data": {"type": t}} for i, t in nodes],
            "edges": [
                {"data": {"sourceHandle": {"id": s, "name": so}, "targetHandle": {"id": t, "fieldName": tf}}}
                for s, so, t, tf in edges
            ],
        }
    }


NODES = [
    ("pair", "WaterInputSet"),
    ("seg_after", "TerraboxGeoRasterThresholdSegmentation"),
    ("seg_before", "TerraboxGeoRasterThresholdSegmentation"),
    ("mask_after", "ToolResultField"),
    ("mask_before", "ToolResultField"),
    ("evidence", "TerraboxGeoWaterWaterEvidence"),
]
MASKS = [
    ("seg_after", "api_run_model", "mask_after", "result"),
    ("seg_before", "api_run_model", "mask_before", "result"),
]


def test_correct_two_date_flow_has_no_errors():
    edges = [
        ("pair", "after_path", "seg_after", "input_path"),
        ("pair", "before_path", "seg_before", "input_path"),
        *MASKS,
        ("mask_after", "value", "evidence", "after_path"),
        ("mask_before", "value", "evidence", "before_path"),
    ]
    assert geo_wiring_errors(_flow(NODES, edges)) == []


def test_threshold_fed_with_another_mask_is_flagged():
    # N041: the before step read the after step's mask; WaterEvidence then refused (valid_mask_mismatch).
    edges = [
        ("pair", "after_path", "seg_after", "input_path"),
        ("seg_after", "api_run_model", "mask_after", "result"),
        ("mask_after", "value", "seg_before", "input_path"),
    ]
    errors = geo_wiring_errors(_flow(NODES, edges))
    assert len(errors) == 1
    assert errors[0].startswith("seg_before: input_path comes from the mask written by seg_after")


def test_both_dates_from_the_same_scene_are_flagged():
    edges = [("pair", "after_path", "seg_after", "input_path"), ("pair", "after_path", "seg_before", "input_path")]
    assert any("before_path" in e and "after_path" in e for e in geo_wiring_errors(_flow(NODES, edges)))


def test_swapped_evidence_inputs_are_flagged():
    edges = [
        ("pair", "after_path", "seg_after", "input_path"),
        ("pair", "before_path", "seg_before", "input_path"),
        *MASKS,
        ("mask_after", "value", "evidence", "before_path"),
        ("mask_before", "value", "evidence", "after_path"),
    ]
    assert len(geo_wiring_errors(_flow(NODES, edges))) == 2


def test_wiring_errors_are_fixable():
    assert classify_run_error("Geo wiring error: seg_before: input_path ...") is RunErrorKind.FIXABLE


def impact_flow():
    nodes = [
        *NODES,
        ("gate", "TerraboxGeoWaterRasterProfilePreflight"),
        ("threshold", "ToolResultField"),
        ("align", "TerraboxGeoWaterAlignRaster"),
        ("aligned", "ToolResultField"),
        ("impact", "TerraboxGeoWaterWaterByClass"),
        ("compare", "TerraboxGeoWaterCompareWithReference"),
    ]
    edges = [
        *MASKS,
        ("pair", "before_path", "seg_before", "input_path"),
        ("pair", "after_path", "seg_after", "input_path"),
        ("pair", "before_path", "gate", "before_path"),
        ("pair", "after_path", "gate", "after_path"),
        ("gate", "api_run_model", "seg_before", "preconditions"),
        ("gate", "api_run_model", "seg_after", "preconditions"),
        ("seg_after", "api_run_model", "threshold", "result"),
        ("threshold", "value", "seg_before", "threshold"),
        ("pair", "after_path", "align", "target_path"),
        ("align", "api_run_model", "aligned", "result"),
        ("aligned", "value", "impact", "class_path"),
        ("mask_before", "value", "impact", "before_path"),
        ("mask_after", "value", "impact", "after_path"),
        ("mask_after", "value", "compare", "predicted_path"),
    ]
    flow = _flow(nodes, edges)
    configs = {"seg_before": {"method": "fixed"}, "threshold": {"field_path": "outputs.threshold"}}
    for node in flow["data"]["nodes"]:
        node["data"]["node"] = {"template": {k: {"value": v} for k, v in configs.get(node["id"], {}).items()}}
    return flow


def test_impact_accepts_shared_threshold_gated_aligned_chain():
    assert geo_wiring_errors(impact_flow()) == []


def test_impact_rejects_disconnected_preflight():
    flow = impact_flow()
    flow["data"]["edges"] = [
        e for e in flow["data"]["edges"] if e["data"]["targetHandle"]["fieldName"] != "preconditions"
    ]
    assert any("side branch" in e for e in geo_wiring_errors(flow))


def test_impact_rejects_path_extracted_as_threshold():
    flow = impact_flow()
    next(n for n in flow["data"]["nodes"] if n["id"] == "threshold")["data"]["node"]["template"]["field_path"][
        "value"
    ] = "outputs.output_path"
    assert any("shared threshold" in e for e in geo_wiring_errors(flow))


def test_impact_rejects_missing_alignment_and_different_reference_prediction():
    flow = impact_flow()
    flow["data"]["edges"] = [
        e
        for e in flow["data"]["edges"]
        if e["data"]["targetHandle"]["fieldName"] not in {"class_path", "predicted_path"}
    ]
    errors = geo_wiring_errors(flow)
    assert any("class_path" in e for e in errors)
    assert any("SAME after" in e for e in errors)


async def test_runner_rejects_bad_impact_before_building_graph():
    from unittest.mock import AsyncMock, patch

    from terraflow.agentic.services.flow_run import run_working_flow

    flow = impact_flow()
    flow["data"]["edges"] = [
        e for e in flow["data"]["edges"] if e["data"]["targetHandle"]["fieldName"] != "preconditions"
    ]
    with patch("terraflow.agentic.services.flow_run.build_graph_from_data", new_callable=AsyncMock) as build:
        result = await run_working_flow(flow_data=flow, flow_id="synthetic", user_id="synthetic")
    assert "Geo wiring error" in result["error"]
    build.assert_not_called()


def test_single_scene_classification_remains_supported():
    flow = _flow([("classes", "TerraboxGeoWaterWaterByClass")], [])
    assert geo_wiring_errors(flow) == []


def test_impact_rejects_inconsistent_mask_semantics():
    flow = impact_flow()
    node = next(n for n in flow["data"]["nodes"] if n["id"] == "seg_before")
    node["data"]["node"]["template"]["direction"] = {"value": "above"}
    assert any("label semantics" in e for e in geo_wiring_errors(flow))
