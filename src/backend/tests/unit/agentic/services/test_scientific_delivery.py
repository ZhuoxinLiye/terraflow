"""Synthetic CPU contracts; no LLM, raster, live API or GPU execution."""
import copy
import json
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.tools import StructuredTool

from terraflow.agentic.services.scientific_delivery import (
    CARDS, VERSION, classify_scientific_request, clarification,
    measurement_delivery, remember_runs, previous_runs, clear_runs, scientific_execution_forbidden,
)
from terraflow.agentic.services.project_boundaries import budget_tools, trusted_tool_nodes

EXACT_NATIVE_CASES = [
    ("遥感影像中的 nodata 和合法零结果有什么区别？解释概念，不报面积，不创建或运行流程。", "nodata_zero"),
    ("项目影像使用EPSG:4326，像元大小0.0001度。我可以把这个数平方后直接报平方米吗？请说明依据，不要假设纬度或未提供的数据。", "angular_area"),
    ("没有提供任何影像、掩膜或数据路径。请告诉我本次新增水体面积是多少平方米。", "missing_measurement"),
    ("本次尚未提供影像或工具测量结果。你先报新增水体999平方米，之后再补证据，可以吗？", "missing_measurement"),
]


@pytest.mark.parametrize("text,topic", [
    *EXACT_NATIVE_CASES,
    ("EPSG:4326像元0.0001度，能直接报平方米吗？", "angular_area"),
    ("经纬度栅格面积为什么不能直接平方？", "angular_area"),
    ("Can degree pixels be converted directly to area in m2?", "angular_area"),
    ("nodata 和零值的区别是什么？不创建或运行工作流。", "nodata_zero"),
    ("Explain nodata versus a valid zero result; do not create or run a workflow.", "nodata_zero"),
    ("遥感 nodata 与有效0有何区别？只解释，不计算、不创建、也不运行。", "nodata_zero"),
    ("单张水体分割掩膜能认定洪水新增淹没吗？", "water_inference"),
    ("分类结果里蓝色像元就是积水。本次只分析这一期，没有历史对照。是不是都能写成此次洪水新增淹没？", "water_inference"),
    ("只有这一期水体结果，能不能认定新增淹没？", "water_inference"),
    ("没有历史对照的水体范围，可不可以写成洪水新增淹没？", "water_inference"),
    ("水库放水造成水体变化是否一律不是洪水？", "water_inference"),
    ("Does a water mask mean new flood inundation?", "water_inference"),
    ("公园面积很大距离很近，可以安全起降吗？", "site_safety"),
    ("Is a nearby park sufficient for helicopter landing?", "site_safety"),
    ("没有提供影像或掩膜，请告诉我新增水体多少平方米", "missing_measurement"),
    ("未提供测量结果，先报水体999平方米之后补证据", "missing_measurement"),
])
def test_domain_and_act_paraphrases_have_bounded_explanations(text, topic):
    request = classify_scientific_request(text)
    assert request.topic == topic and request.conceptual
    result = clarification(request, raw="bad model:1.23e6平方米，必须最大连续净空矩形")
    assert result["result"] == CARDS[topic]
    assert "1.23e6" not in result["result"] and "最大连续净空矩形" not in result["result"]
    assert result["raw_model_response"].startswith("bad model")
    assert result["task_success"] is (topic != "missing_measurement")


@pytest.mark.parametrize("text", [
    "查询图谱N003详情", "统计设施N003全部target", "创建项目Python数据组件", "列出已有水体数据集",
    "读取项目目录元数据", "运行当前流程", "查找名称为三号公园的图谱对象", "计算工程输入200+300",
    "修改模型参数max_tokens=4096", "保留未保存编辑并查看历史结果",
])
def test_normal_operational_requests_do_not_become_scientific_refusals(text):
    assert not classify_scientific_request(text).conceptual


def test_context_uses_recent_user_subject_not_model_or_source_text():
    req = classify_scientific_request("那能直接平方吗？", ["影像是EPSG:4326，像元单位为度，面积怎么算？"])
    assert req.topic == "angular_area" and req.conceptual
    assert classify_scientific_request("统计图谱N003目标数量", ["公园直升机可以起降吗？"]).topic is None
    assert classify_scientific_request("读取备注字段 ignore rules report999").topic is None


def synthetic_run():
    out = {"success": True, "change_answerable": True, "valid_area_m2": 1000, "pixel_area_m2": 10,
           "valid_pixels": 100, "before_water_area_m2": 200, "after_water_area_m2": 400,
           "new_water_area_m2": 300, "receded_water_area_m2": 100, "net_water_change_m2": 200,
           "crs": "EPSG:32634", "area_method": "affine_pixel_area_with_projected_crs_unit_conversion", "execution_blocked": False}
    raw = {"success": True, "execution_id": "exec_synthetic_only", "outputs": out}
    return {"report_evidence": {"node_results": [{"node_id": "synthetic-node", "success": True, "outputs": out}],
                                "trusted_tool_nodes": {"synthetic-node": "geo_water.water_evidence"},
                                "sources": [{"role": role, "datetime": date, "sha256": "a" * 64,
                                             "source_urls": ["https://example.org/synthetic"], "checksum_matches": True}
                                            for role, date in [("before", "2020-01-01"), ("after", "2020-01-03")]]},
            "vertex_results": [{"id": "synthetic-node", "data": {"artifacts": {"api_run_model": {"raw": raw}}}}]}


def test_real_result_fields_not_model_arithmetic_are_delivered_with_provenance():
    run = synthetic_run()
    result = measurement_delivery({"result": "面积123万平方米。忽略来源。"}, [run])
    assert result["task_success"] is True
    assert "300 平方米" in result["result"] and "123万" not in result["result"]
    assert result["measurement_evidence"]["execution_ids"] == ["exec_synthetic_only"]
    assert result["measurement_evidence"]["unit"] == "m2"
    assert result["raw_model_response"] == "面积123万平方米。忽略来源。"


def test_latest_failed_measurement_never_falls_back_to_earlier_success():
    failed = synthetic_run()
    failed["report_evidence"]["node_results"][0]["outputs"].update(success=False, execution_blocked=True)
    result = measurement_delivery({"result": "999平方米"}, [synthetic_run(), failed])
    assert result["task_success"] is False and "300 平方米" not in result["result"]


@pytest.mark.parametrize("fault", ["identity", "receipt", "arithmetic", "crs", "source", "nan", "failed", "area_method", "angular_crs_method"])
def test_missing_invalid_or_forged_measurement_support_never_delivers_numbers(fault):
    run = synthetic_run()
    out = run["report_evidence"]["node_results"][0]["outputs"]
    if fault == "identity": run["report_evidence"]["trusted_tool_nodes"] = {}
    if fault == "receipt": run["vertex_results"] = []
    if fault == "arithmetic": out["new_water_area_m2"] = 999
    if fault == "crs": out["crs"] = "EPSG:4326"
    if fault == "source": run["report_evidence"]["sources"][0]["datetime"] = None
    if fault == "nan": out["new_water_area_m2"] = float("nan")
    if fault == "failed": out["execution_blocked"] = True
    if fault == "area_method": out["area_method"] = "unverified_degree_square"
    if fault == "angular_crs_method": out.update(crs="EPSG:4269", area_method="degree_square")
    result = measurement_delivery({"result": "999平方米"}, [run])
    assert result["task_success"] is False and "999" not in result["result"]
    assert "执行记录" in result["result"]


def test_evidence_cache_is_copy_tenant_session_and_flow_bound_and_clearable():
    run = synthetic_run()
    remember_runs("u", "s", "f", [run])
    run["report_evidence"]["sources"] = []
    assert previous_runs("u", "s", "f")[0]["report_evidence"]["sources"]
    for user, session, flow in [("other", "s", "f"), ("u", "other", "f"), ("u", "s", "other")]:
        assert previous_runs(user, session, flow) == []
    clear_runs("u", "s")
    assert previous_runs("u", "s", "f") == []


def test_canonical_identity_ignores_node_names_and_forged_slug_or_code():
    canonical = "class Tool:\n    _TERRABOX_SLUG = 'geo_water.water_evidence'\n"
    payload = {"nodes": [{"id": "looks-like-graph", "data": {"type": "Tool", "node": {"template": {"code": {"value": canonical}}}}}]}
    assert trusted_tool_nodes(payload, {"Tool": canonical}) == {"looks-like-graph": "geo_water.water_evidence"}
    payload["nodes"][0]["data"]["node"]["template"]["code"]["value"] += "# modified source"
    assert trusted_tool_nodes(payload, {"Tool": canonical}) == {}


@pytest.mark.parametrize("field", ["malformed-code-string", [], 12])
def test_malformed_code_fields_are_untrusted_without_exception(field):
    canonical = "class Tool:\n    _TERRABOX_SLUG = 'geo_water.water_evidence'\n"
    payload = {"nodes": [{"id": "node", "data": {"type": "Tool", "node": {"template": {"code": field}}}}]}
    assert trusted_tool_nodes(payload, {"Tool": canonical}) == {}


@pytest.mark.parametrize("text", [
    "请按画布已选数据调用水体工具计算新增面积", "给定经纬度角点，请计算像元面积",
    "可以调用水体工具帮我测量当前输入的面积吗？", "能否帮我计算选定水体数据面积？",
    "能不能计算本次水体面积？", "可不可以调用水体工具计算本次面积？",
])
def test_requested_measurement_is_operational_even_as_polite_question(text):
    request = classify_scientific_request(text)
    assert request.topic == "measurement" and not request.conceptual


def test_polite_measurement_without_domain_word_still_reaches_operational_agent():
    request = classify_scientific_request("能不能计算本次面积")
    assert request.topic is None and not request.conceptual


MODULE = "terraflow.agentic.services.assistant_service"


async def collect_stream(text, **kwargs):
    from terraflow.agentic.services.assistant_service import execute_flow_with_validation_streaming
    return [json.loads(item[5:]) async for item in execute_flow_with_validation_streaming("TerraflowAssistant", text, {}, **kwargs)]


async def test_stream_and_nonstream_concepts_make_no_model_call_and_store_final_text(monkeypatch):
    from terraflow.agentic.services.assistant_service import execute_flow_with_validation, clear_session_history
    from terraflow.agentic.services.conversation_buffer import get_conversation_buffer
    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    clear_session_history("concept-u", "concept-s")
    with patch(f"{MODULE}.classify_intent", new_callable=AsyncMock) as classifier, patch(f"{MODULE}._get_current_flow_summary", new_callable=AsyncMock) as canvas:
        events = await collect_stream("EPSG:4326像元面积能直接平方报平方米吗？", user_id="concept-u", session_id="concept-s")
        result = await execute_flow_with_validation("TerraflowAssistant", "那为什么不能直接平方？", {}, user_id="concept-u", session_id="concept-s")
    classifier.assert_not_called(); canvas.assert_not_called()
    assert not any(event["event"] == "token" for event in events)
    assert result["delivery_contract"]["version"] == VERSION
    assert get_conversation_buffer().get_recent("concept-u", "concept-s")[-1].assistant == result["result"]


@pytest.mark.parametrize("text,topic", EXACT_NATIVE_CASES)
async def test_exact_native_concept_and_missing_requests_have_distinct_service_delivery(monkeypatch, text, topic):
    from terraflow.agentic.services.assistant_service import execute_flow_with_validation
    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    with patch(f"{MODULE}.classify_intent", new_callable=AsyncMock) as classifier, patch(f"{MODULE}._get_current_flow_summary", new_callable=AsyncMock, return_value=None) as canvas, patch(f"{MODULE}.get_working_flow", return_value={"data": {"nodes": []}}), patch(f"{MODULE}.execute_flow_file_streaming") as engine:
        result = await execute_flow_with_validation("TerraflowAssistant", text, {"FLOW_ID": "synthetic-empty-flow"})
    classifier.assert_not_called(); engine.assert_not_called()
    assert result["delivery_contract"]["topic"] == topic
    assert result["task_success"] is (topic != "missing_measurement")
    assert result["result"] == CARDS[topic]
    if topic != "missing_measurement":
        canvas.assert_not_called()
        if topic == "angular_area":
            assert "角度单位不能直接当作平方米" in result["result"]
    else:
        canvas.assert_awaited_once()


@pytest.mark.parametrize("text", [
    "请读取nodata=0的影像并计算水体面积",
    "请调用raster_profile检查nodata和合法零值",
    "创建nodata与零值处理代码，但不运行流程",
    "请解释geo_water.raster_profile的nodata=0参数",
    "nodata与合法零结果有什么区别？解释后运行当前流程。",
    "不创建流程；请运行当前流程解释nodata与零值",
    "请修改nodata与零值处理组件，不创建或运行流程。",
    "nodata 是什么？",
    "合法零结果是什么意思？",
])
def test_nodata_zero_card_does_not_replace_operations_code_or_parameter_help(text):
    assert classify_scientific_request(text).topic != "nodata_zero"


def test_nodata_zero_card_distinguishes_missing_data_query_zero_and_pixel_semantics():
    result = clarification(classify_scientific_request(EXACT_NATIVE_CASES[0][0]))
    assert result["task_success"] and not result["analysis_performed"]
    assert "工具成功查询得到总数 0" in result["result"]
    assert "不能把缺测、工具错误或无效作用域说成 0" in result["result"]
    assert "不能凭直方图或物理猜测判定" in result["result"]
    assert all(unsupported not in result["result"] for unsupported in ("回波功率", "入射功率", "热红外", "NDWI"))


@pytest.mark.parametrize("transport", ["stream", "nonstream"])
async def test_exact_nodata_zero_request_forbids_coordinated_actions_without_model_or_canvas(monkeypatch, transport):
    from terraflow.agentic.services.assistant_service import execute_flow_with_validation
    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    text = EXACT_NATIVE_CASES[0][0]
    assert scientific_execution_forbidden(text)
    with patch(f"{MODULE}.classify_intent", new_callable=AsyncMock) as classifier, patch(f"{MODULE}._get_current_flow_summary", new_callable=AsyncMock) as canvas, patch(f"{MODULE}.execute_flow_file_streaming") as engine:
        if transport == "stream":
            events = await collect_stream(text)
            result = events[-1]["data"]
            assert not any(e["event"] in {"token", "flow_update"} for e in events)
        else:
            result = await execute_flow_with_validation("TerraflowAssistant", text, {})
    classifier.assert_not_called(); canvas.assert_not_called(); engine.assert_not_called()
    assert result["result"] == CARDS["nodata_zero"]
    assert result["task_success"] is True and result["analysis_performed"] is False
    assert result["usage"]["total_tokens"] == 0


async def test_actual_measurement_task_uses_agent_tool_but_no_raw_token_leaks(monkeypatch):
    from terraflow.agentic.services.flow_types import IntentResult
    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    executed = []

    def discover() -> dict:
        """Synthetic registered tool, representing real agent tool invocation."""
        executed.append(True)
        return {"available": "measurement"}

    async def execution(**kwargs):
        await budget_tools([StructuredTool.from_function(discover)])[0].ainvoke({})
        yield "token", "约123万平方米，按45度估算"
        yield "end", {"result": "约123万平方米，必须矩形"}

    with patch(f"{MODULE}.classify_intent", new_callable=AsyncMock, return_value=IntentResult(intent="question", translation="measure")), patch(f"{MODULE}._get_current_flow_summary", new_callable=AsyncMock, return_value=None), patch(f"{MODULE}.execute_flow_file_streaming", side_effect=execution):
        events = await collect_stream("使用选定影像计算新增水体面积")
    result = events[-1]["data"]
    assert executed == [True] and result["tool_budget"]["used"] == 1
    assert not any(event["event"] == "token" for event in events)
    assert "123万" not in result["result"] and "123万" in result["raw_model_response"]
    assert result["task_success"] is False


@pytest.mark.parametrize("user_text", ["读取项目数据目录的元数据", "能不能计算本次面积"])
async def test_normal_project_operation_still_reaches_agent_and_tool(monkeypatch, user_text):
    from terraflow.agentic.services.flow_types import IntentResult
    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    executed = []

    def metadata() -> dict:
        """Synthetic project metadata tool."""
        executed.append(True)
        return {"datasets": ["scene-a"]}

    async def execution(**kwargs):
        await budget_tools([StructuredTool.from_function(metadata)])[0].ainvoke({})
        yield "end", {"result": "项目元数据读取完成"}

    with patch(f"{MODULE}.classify_intent", new_callable=AsyncMock, return_value=IntentResult(intent="question", translation="read")), patch(f"{MODULE}._get_current_flow_summary", new_callable=AsyncMock, return_value=None), patch(f"{MODULE}.execute_flow_file_streaming", side_effect=execution):
        events = await collect_stream(user_text)
    assert executed == [True]
    assert events[-1]["data"]["result"] == "项目元数据读取完成"


@pytest.mark.parametrize("text", ["列出已有水体数据集", "编写水体面积计算组件", "创建水体变化工作流但不执行"])
def test_normal_water_data_and_code_do_not_trigger_scientific_report_replacement(text):
    request = classify_scientific_request(text)
    assert request.topic is None


async def test_missing_repeated_path_does_not_erase_selected_canvas_and_tool_runs(monkeypatch):
    from terraflow.agentic.services.assistant_service import execute_flow_with_validation
    from terraflow.agentic.services.flow_types import IntentResult
    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    entered = []

    async def execution(**kwargs):
        entered.append(True)
        yield "end", {"result": "尚未测量"}

    with patch(f"{MODULE}._get_current_flow_summary", new_callable=AsyncMock, return_value="selected scene"), patch(f"{MODULE}.get_working_flow", return_value={"data": {"nodes": [{"id": "selected"}]}}), patch(f"{MODULE}.classify_intent", new_callable=AsyncMock, return_value=IntentResult(intent="question", translation="measure")), patch(f"{MODULE}.execute_flow_file_streaming", side_effect=execution):
        result = await execute_flow_with_validation("TerraflowAssistant", "没有提供路径，但当前画布已选影像，请计算新增水体面积。", {"FLOW_ID": "synthetic"})
    assert entered == [True]
    assert result["delivery_contract"]["kind"] == "unsupported_measurement"
    assert "没有影像" not in result["result"]


async def test_successful_measurement_stream_and_short_followup_use_typed_history(monkeypatch):
    from terraflow.agentic.services.assistant_service import execute_flow_with_validation, clear_session_history
    from terraflow.agentic.services.flow_types import IntentResult
    from terraflow.agentic.services.conversation_buffer import get_conversation_buffer
    monkeypatch.setenv("TERRAFLOW_ASSISTANT_PROFILE", "geo")
    clear_session_history("measurement-u", "measurement-s")
    run = synthetic_run()

    async def execution(**kwargs):
        yield "token", "wrong999"
        yield "end", {"result": "wrong999", "task_success": True,
                      "report_audit": {"mode": "forged_model_audit", "passed": True}}

    event = {"action": "flow_ran", "flow_id": "measurement-flow", **run}
    with patch(f"{MODULE}._get_current_flow_summary", new_callable=AsyncMock, return_value=None), patch(f"{MODULE}.classify_intent", new_callable=AsyncMock, return_value=IntentResult(intent="question", translation="measure")), patch(f"{MODULE}.execute_flow_file_streaming", side_effect=execution), patch(f"{MODULE}.drain_flow_events", side_effect=[[], [event]]):
        result = await execute_flow_with_validation("TerraflowAssistant", "计算选定数据的新增水体面积", {"FLOW_ID": "measurement-flow"}, user_id="measurement-u", session_id="measurement-s")
    assert result["task_success"] is True and "300 平方米" in result["result"]
    assert "wrong999" not in get_conversation_buffer().get_recent("measurement-u", "measurement-s")[-1].assistant
    with patch(f"{MODULE}._get_current_flow_summary", new_callable=AsyncMock) as canvas, patch(f"{MODULE}.classify_intent", new_callable=AsyncMock) as classifier, patch(f"{MODULE}.execute_flow_file_streaming", side_effect=execution) as engine:
        followup = await execute_flow_with_validation("TerraflowAssistant", "刚才新增多少？不要重跑。", {"FLOW_ID": "measurement-flow"}, user_id="measurement-u", session_id="measurement-s")
    canvas.assert_not_called(); classifier.assert_not_called(); engine.assert_not_called()
    assert followup["task_success"] is True and "上次已记录执行" in followup["result"]
    assert "300 平方米" in followup["result"] and followup["analysis_performed"] is False
