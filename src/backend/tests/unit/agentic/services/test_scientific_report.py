"""Synthetic arithmetic and provenance fixtures; not satellite accuracy tests."""

import copy
import hashlib
import json

from terraflow.agentic.services.scientific_report import (
    constrained_delivery,
    input_evidence,
    model_summary,
    report_facts,
)


def evidence():
    support = {
        "valid_pixels": 100,
        "pixel_area_m2": 10000,
        "valid_area_m2": 1000000,
        "area_method": "synthetic_projected",
        "crs": "EPSG:32634",
        "grid_id": "synthetic",
        "excluded_pixels": 2,
        "shape": [10, 10],
        "transform": [100, 0, 0, 0, -100, 1000],
    }
    change = {
        **support,
        "change_answerable": True,
        "before_water_area_m2": 100000,
        "after_water_area_m2": 400000,
        "new_water_area_m2": 350000,
        "receded_water_area_m2": 50000,
        "net_water_change_m2": 300000,
    }
    classes = {
        **support,
        "class_answerable": True,
        "total_new_water_area_m2": 350000,
        "classes": [
            {
                "value": 40,
                "name": "synthetic_crop",
                "class_area_m2": 1000000,
                "water_area_m2": 400000,
                "new_water_area_m2": 350000,
                "new_water_fraction_of_class": 0.35,
                "share_of_new_water": 1,
            }
        ],
    }
    ref = {
        **support,
        "comparison_answerable": True,
        "predicted_water_area_m2": 400000,
        "reference_water_area_m2": 500000,
        "agreement_area_m2": 300000,
        "predicted_only_area_m2": 100000,
        "reference_only_area_m2": 200000,
        "area_difference_m2": -100000,
    }
    raster = {"coverage_bbox_wgs84": [0, 0, 1, 1]}
    threshold = {"threshold": -15, "input_transform": "db", "direction": "below"}
    return {
        "node_results": [
            {"node_id": f"synthetic-{i}", "outputs": r}
            for i, r in enumerate([
                change,
                classes,
                ref,
                raster,
                threshold,
                threshold,
                {"common_valid_pixels": 100, "before": {"nodata": [-32768]}, "after": {"nodata": [-32768]}},
                {"resampling": "nearest", "source_nodata": 0, "output_nodata": 0},
            ])
        ],
        "trusted_tool_nodes": {"synthetic-0": "geo_water.water_evidence", "synthetic-1": "geo_water.water_by_class",
                               "synthetic-2": "geo_water.compare_with_reference", "synthetic-3": "geo_water.rasterize_reference"},
        "sources": [
            {"role": role, "datetime": date, "source_urls": ["https://example.org/synthetic"], "input_scale": "linear"}
            for role, date in [
                ("before", "2023-01-01T00:00:00Z"),
                ("after", "2023-01-13T00:00:00Z"),
                ("classification", "2021-01-01T00:00:00Z"),
                ("vector", "2023-01-07T00:00:00Z"),
            ]
        ],
    }


def test_delivery_keeps_raw_but_uses_distinct_new_and_after_denominators_and_actions():
    raw = "Saved a card. Input was dB. 35% after-water coverage. Whole task took 1s."
    result = constrained_delivery(
        {"result": raw},
        {"report_evidence": evidence(), "metrics": {"duration_seconds": 1, "total_tokens": 0}, "reuse_proposal": False},
        duration=123,
        usage={"total_tokens": 456},
    )
    assert result["raw_model_response"] == raw
    assert result["report_audit"]["passed"]
    assert not result["report_audit"]["raw_prose_certified"]
    assert "0.3500|35.0000|100.0000|40.0000" in result["result"]
    assert "没有生成复用保存卡" in result["result"]
    assert "123.000" in result["result"] and "456" in result["result"]
    assert "2023-01-07T00:00:00Z" in result["result"]


def test_wrong_fraction_blocks_conclusions():
    data = evidence()
    data["node_results"][1]["outputs"]["classes"][0]["new_water_fraction_of_class"] = 0.4
    assert "measurement_or_denominator_mismatch" in report_facts(data)[1]


def test_failed_tool_missing_date_checksum_and_threshold_mismatch_are_rejected():
    base = evidence()
    cases = []
    data = copy.deepcopy(base)
    data["node_results"][0]["outputs"]["execution_blocked"] = True
    cases.append(data)
    data = copy.deepcopy(base)
    data["sources"][0]["datetime"] = None
    cases.append(data)
    data = copy.deepcopy(base)
    data["sources"][0]["checksum_matches"] = False
    cases.append(data)
    data = copy.deepcopy(base)
    data["node_results"].pop(5)
    cases.append(data)
    data = copy.deepcopy(base)
    data["sources"].pop()
    cases.append(data)
    for data in cases:
        result = constrained_delivery({"result": "success"}, {"report_evidence": data}, duration=1, usage={})
        assert not result["report_audit"]["passed"]
        assert "暂不交付统计结论" in result["result"]


def test_unsupported_chat_is_unchanged():
    assert constrained_delivery({"result": "hello"}, {}, duration=1, usage={}) == {"result": "hello"}


def test_actual_used_stac_asset_is_hashed_and_unused_asset_is_not_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("TERRAFLOW_WATER_RUNTIME_DIR", str(tmp_path))
    path = tmp_path / "test.tif"
    path.write_bytes(b"synthetic bytes, not a satellite raster")
    item = tmp_path / "catalog/collections/test/items/test.json"
    item.parent.mkdir(parents=True)
    stac = {
        "id": "synthetic",
        "properties": {"datetime": "2021-01-01T00:00:00Z", "workspace:data_type": "classification"},
        "assets": {
            "data": {"href": str(path), "file:checksum": "1220" + hashlib.sha256(path.read_bytes()).hexdigest()}
        },
        "links": [{"rel": "derived_from", "href": "https://example.org/synthetic"}],
    }
    item.write_text(json.dumps(stac))
    rows = [{"outputs": {"source_id": str(path)}}]
    assert input_evidence({}, [], rows)[0]["checksum_matches"] is True
    assert input_evidence({}, [], []) == []
    path.write_bytes(b"changed")
    assert input_evidence({}, [], rows)[0]["checksum_matches"] is False


def test_model_summary_keeps_sources_and_all_denominators_once_with_alias_deduplication():
    data = evidence()
    data["sources"].append({**data["sources"][0], "path": "/synthetic/alias.tif"})
    facts, errors = report_facts(data)
    assert not errors
    summary = json.loads(model_summary(data, facts))
    assert len(summary["sources"]) == 4
    assert summary["measurements"]["classes"]["classes"][0]["new_water_fraction_of_class"] == 0.35
    assert summary["measurements"]["classes"]["classes"][0]["water_area_m2"] == 400000
    assert summary["sources"][0]["datetime"] == "2023-01-01T00:00:00Z"
    assert summary["grid"]["crs"] == "EPSG:32634"
    assert summary["raw_nodata"]["before"] == [-32768]
