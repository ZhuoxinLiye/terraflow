"""Explicit synthetic CPU evidence; not satellite/model/benchmark results."""
import copy

import pytest

from terraflow.agentic.services.graph_delivery import constrained_graph_delivery


SHA = "a" * 64
TRUSTED = {"actual-query": "graph_query.query_nodes"}
REQUEST = "请查询图谱中设施 N003 的全部目标记录并计数，limit=1。不要添加业务类别或风险筛选。"


def output(**changes):
    result = {"success": True, "ok": True, "execution_blocked": False, "count": 3, "returned_count": 1,
              "truncated": True, "nodes": [{"id": "S-T1"}], "filters_applied": {"facility_id": "N003", "node_type": "target"},
              "count_semantics": "total_matches_before_limit", "count_unit": "annotation_records",
              "provenance": {"dataset_id": "synthetic-only", "snapshot_sha256": SHA, "snapshot_id": "sha256:" + SHA,
                             "source_version": "synthetic-v1", "synthetic": True, "read_only": True,
                             "evidence_kind": "existing_annotation_records", "source_format": "graph_annotations_json"}}
    result.update(changes)
    return result


def deliver(out=None, request=REQUEST, *, trusted=TRUSTED, **kwargs):
    runs = [{"report_evidence": {"node_results": [{"node_id": "actual-query", "success": True, "outputs": out or output()}]}}]
    return constrained_graph_delivery({"result": "unverified invented 999", "success": True}, runs, user_text=request,
                                      trusted_graph_nodes=trusted, **kwargs)


def test_real_shape_success_uses_only_tool_numbers_and_keeps_model_diagnostic():
    result = deliver()
    assert result["task_success"] and result["report_audit"]["passed"]
    assert '"count": 3' in result["result"] and "999" not in result["result"]
    assert result["model_response_original"] == "unverified invented 999"
    assert "已有标注记录" in result["result"] and SHA in result["result"]


def test_valid_zero_is_success():
    result = deliver(output(count=0, returned_count=0, truncated=False, nodes=[]))
    assert result["task_success"] and '"count": 0' in result["result"]


@pytest.mark.parametrize("changes,reason", [
    ({"success": False}, "tool_execution_failed"),
    ({"ok": False}, "tool_execution_failed"),
    ({"execution_blocked": True}, "tool_execution_failed"),
    ({"count": True}, "invalid_count_or_truncation"),
    ({"count": -1}, "invalid_count_or_truncation"),
    ({"returned_count": 2}, "invalid_count_or_truncation"),
    ({"truncated": False}, "invalid_count_or_truncation"),
    ({"count_semantics": "returned_count"}, "invalid_count_semantics"),
    ({"count_unit": "vehicles"}, "invalid_count_unit"),
    ({"by_target_type": {"building": 2}}, "invalid_distribution"),
    ({"filters_applied": {"facility_id": "N003", "node_type": "target", "target_type_contains": "target"}}, "unrequested_business_category"),
    ({"filters_applied": {"facility_id": "N003", "node_type": "target", "risk_level": "unknown"}}, "unrequested_risk_filter"),
    ({"filters_applied": {"facility_id": "N004", "node_type": "target"}}, "unrequested_scope"),
    ({"filters_applied": {"node_type": "target"}}, "requested_facility_scope_missing"),
    ({"provenance": {}}, "invalid_snapshot_provenance"),
])
def test_bad_evidence_or_extra_filters_veto_numeric_delivery(changes, reason):
    result = deliver(output(**changes))
    assert not result["task_success"] and reason in result["report_audit"]["reason_codes"]
    assert '"count"' not in result["result"] and "999" not in result["result"]


def test_explicit_category_request_is_permitted():
    result = deliver(output(filters_applied={"facility_id": "N003", "node_type": "target", "target_type_contains": "aviation_area"}),
                     request="请用图谱计数设施 N003 的航空类别标注，target_type_contains=aviation_area。")
    assert result["task_success"]


@pytest.mark.parametrize("reason", ["invalid_scope", "ambiguous_name"])
def test_failure_is_not_zero_and_ambiguity_keeps_only_candidate_ids(reason):
    out = output(success=False, ok=False, execution_blocked=True, reason_code=reason,
                 error={"code": reason, "candidates": [{"id": "S-F1", "label": "private-name"}, {"id": "S-F2"}]})
    result = deliver(out)
    assert not result["task_success"] and reason in result["result"]
    assert "private-name" not in result["result"] and '"count"' not in result["result"]
    assert "S-F1" in result["result"] and "S-F2" in result["result"]


def test_arbitrary_node_even_with_matching_output_cannot_claim_graph_execution():
    result = deliver(trusted={})
    assert not result["task_success"] and "no_trusted_graph_tool_results" in result["result"]


def test_missing_requested_operation_is_task_failure():
    result = deliver(request=REQUEST + "另按精确ID读取详情并查找候选。")
    assert not result["task_success"] and "requested_graph_operation_missing" in result["result"]


def test_unrelated_request_unchanged_without_trusted_graph_run():
    original = {"result": "unrelated"}
    assert constrained_graph_delivery(original, [], user_text="你好") is original


def test_history_requires_explicit_followup_and_uses_same_actual_evidence():
    historical = [{"report_evidence": {"node_results": [{"node_id": "actual-query", "success": True, "outputs": output()}]}}]
    previous = constrained_graph_delivery({"result": "999"}, [], user_text="继续解释刚才图谱计数", recent_user_texts=[REQUEST],
                                          prior_runs=historical, trusted_graph_nodes=TRUSTED)
    assert previous["task_success"] and previous["report_audit"]["history_used"]
    no_history = constrained_graph_delivery({"result": "999"}, [], user_text=REQUEST, prior_runs=historical, trusted_graph_nodes=TRUSTED)
    assert not no_history["task_success"] and "no_actual_graph_execution" in no_history["result"]


def test_input_structures_are_not_mutated():
    out = output()
    before = copy.deepcopy(out)
    deliver(out)
    assert out == before


def test_runner_attested_identity_is_used_without_explicit_override():
    run = {"report_evidence": {"node_results": [{"node_id": "actual-query", "success": True, "outputs": output()}],
                               "trusted_tool_nodes": TRUSTED}}
    result = constrained_graph_delivery({"result": "999"}, [run], user_text=REQUEST)
    assert result["task_success"]


def test_latest_failure_never_falls_back_to_earlier_success():
    good = {"report_evidence": {"node_results": [{"node_id": "actual-query", "success": True, "outputs": output()}],
                                "trusted_tool_nodes": TRUSTED}}
    bad = copy.deepcopy(good)
    bad["report_evidence"]["node_results"][0]["outputs"].update(success=False, reason_code="invalid_scope")
    result = constrained_graph_delivery({"result": "999"}, [good, bad], user_text=REQUEST)
    assert not result["task_success"] and "invalid_scope" in result["result"]


@pytest.mark.parametrize("text", [
    "请解释query_nodes的参数含义，不运行分析。",
    "图谱工具metadata里的synthetic、read_only和snapshot_id字段是什么意思？",
    "get_item如何使用，介绍item_id参数。",
    "query_nodes的count字段与returned_count字段有什么区别？只说明schema。",
])
def test_normal_tool_schema_and_metadata_help_does_not_require_execution(text):
    original = {"result": "正常工具合同说明"}
    assert constrained_graph_delivery(original, [], user_text=text) is original


def test_do_not_rerun_explicit_history_question_still_reads_actual_evidence():
    run = {"report_evidence": {"node_results": [{"node_id": "actual-query", "success": True, "outputs": output()}],
                               "trusted_tool_nodes": TRUSTED}}
    result = constrained_graph_delivery({"result": "999"}, [], user_text="不要运行新分析，请解释刚才图谱计数结果的含义。",
                                        recent_user_texts=[REQUEST], prior_runs=[run])
    assert result["task_success"] and result["report_audit"]["history_used"]


def test_detail_member_count_is_not_compared_to_explicit_different_hierarchy_zero():
    detail = output(item_id="N003", item_type="facility", parents=[{"id": "S-A"}], member_count=3)
    query = output(count=0, returned_count=0, nodes=[], truncated=False,
                   filters_applied={"facility_id": "N003", "node_type": "facility"})
    run = {"report_evidence": {"trusted_tool_nodes": {"detail": "graph_query.get_item", "query": "graph_query.query_nodes"},
        "node_results": [{"node_id": "detail", "success": True, "outputs": detail}, {"node_id": "query", "success": True, "outputs": query}]}}
    result = constrained_graph_delivery({"result": "999"}, [run], user_text="读取图谱设施 N003 的详情，并按facility_id=N003, node_type=facility计数。")
    assert result["task_success"]


def test_specific_graph_result_explanation_is_not_plain_tool_help():
    result = constrained_graph_delivery({"result": "unverified count999"}, [], user_text="请解释图谱设施 N003 的计数结果含义。")
    assert result["task_success"] is False and "999" not in result["result"]
    assert "no_actual_graph_execution" in result["report_audit"]["reason_codes"]
