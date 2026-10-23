"""Synthetic contract tests; no model, imagery download or benchmark execution."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import terraflow_water_demo as demo


class WaterContractTests(unittest.TestCase):
    order = ["raster_viewer.inspect_geotiff", "geo_water.raster_profile_preflight",
             "geo_raster.threshold_segmentation", "geo_water.water_evidence",
             "geo_water.align_raster", "geo_water.water_by_class", "geo_water.compare_with_reference"]

    def validate(self, order):
        return demo.validate_order(order, order, [{"slug": s} for s in self.order], "sar_backscatter", "landcover_impact")

    def test_unsafe_plans_rejected(self):
        self.validate(self.order)
        for left, right in ((1, 2), (3, 4), (4, 5)):
            order = self.order.copy()
            order[left], order[right] = order[right], order[left]
            with self.subTest(order=order), self.assertRaises(demo.DemoError):
                self.validate(order)
        with self.assertRaises(demo.DemoError):
            self.validate(self.order[:-1])

    def test_preflight_blocks_all_downstream_calls(self):
        calls = []
        def fake_call(*args, **kw):
            slug = kw["slug"]
            calls.append(slug)
            out = {"execution_blocked": True, "reason_code": "shape_mismatch"} if slug.endswith("preflight") else {}
            return {"tool_slug": slug, "success": True, "outputs": out}
        with patch.object(demo, "call_tool", fake_call):
            result = demo.run_success_chain("unused", "unused", run_id="synthetic", plan={"execution_order": self.order},
                before="before", after="mismatch", output_dir=Path("unused"), model_state={},
                fixture_meta={"type": "synthetic", "input_kind": "sar_backscatter"})
        self.assertEqual(result["status"], "blocked_by_gate")
        self.assertEqual(calls, self.order[:2])

    def test_success_envelope_with_empty_scientific_outputs_fails(self):
        summary = {"scenario": "landcover_impact", "success_chain": {"status": "success", "steps": [
            {"tool_slug": slug, "success": True, "outputs": {}, "manifest_exists": True} for slug in self.order]}}
        result = demo.scientific_result(summary)
        self.assertTrue(result["checks"]["tool_execution_success"])
        self.assertFalse(result["scientific_task_success"])
        self.assertIn("water_change_answerable", result["failed_checks"])

    def test_empty_model_content_preserves_raw_request_and_response(self):
        response = {"choices": [{"message": {"content": "", "reasoning_content": "synthetic test"}, "finish_reason": "length"}]}
        candidates = [{"slug": s} for s in self.order]
        with tempfile.TemporaryDirectory() as tmp, patch.object(demo, "request_json", return_value=response), patch.object(demo, "applicable_candidates", return_value=candidates):
            with self.assertRaises(demo.DemoError):
                demo.plan_with_model("unused", {"endpoint_model_id": "synthetic"}, {}, input_kind="sar_backscatter", task="landcover_impact", trace_dir=Path(tmp))
            self.assertEqual(json.loads((Path(tmp) / "response.json").read_text()), response)
            self.assertTrue(json.loads((Path(tmp) / "request.json").read_text())["chat_template_kwargs"]["enable_thinking"])


if __name__ == "__main__":
    unittest.main()
