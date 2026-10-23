"""Run the assistant's current canvas flow and surface its result + metrics.

``run_working_flow`` builds a graph from the in-memory canvas, runs it, and
returns the user-facing text (``extract_run_result_text``) plus run metrics
so the agent can both discuss the output and report how the run performed:

- duration: the wall time *measured around the run* — the engine never
  populates ``ResultData.timedelta`` on the returned output vertices, so
  reading it there yields 0.0 (the production "0,0s" bug).
- token usage: summed off the graph's vertices
  (``extract_graph_token_usage``). It lives on each LLM/Agent vertex's
  ``result.token_usage``; the returned output vertices have it ``None``.

Real shapes (duck-typed here so the helpers stay pure/testable and are
resilient to dict-shaped data):
    list[RunOutputs]
      RunOutputs.outputs: list[ResultData | None]
        ResultData.messages: list[ChatOutputResponse]
          ChatOutputResponse.message: str | list[str | dict]
        ResultData.results: Any  (fallback when there are no messages)
    Graph.vertices: list[Vertex]
      Vertex.result: ResultData | None
        ResultData.token_usage: Usage | None  (input/output/total tokens)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from lfx.serialization.serialization import serialize

from terraflow.agentic.helpers.code_security import scan_code_security
from terraflow.agentic.helpers.error_handling import extract_friendly_error
from terraflow.api.utils.flow_utils import build_graph_from_data
from terraflow.processing.process import run_graph_internal

logger = logging.getLogger(__name__)

# Cap so a runaway flow output can't blow the agent's context window or the
# SSE payload (same rationale as the conversation/intent-context caps).
MAX_RESULT_CHARS = 16000
COMPACT_MAX_DEPTH = 5
COMPACT_MAX_STRING = 800

# Hard ceiling on a single assistant-triggered run so a stuck flow can't
# hang the SSE stream forever (AI-runtime resilience requirement).
RUN_TIMEOUT_SECONDS = 120

_NO_OUTPUT = "(no output)"


def compact_value(value: Any, depth: int = 0) -> Any:
    """Retain measurements and support; do not serialize a tool's own schema."""
    if depth > COMPACT_MAX_DEPTH:
        return "[details in node output]"
    if isinstance(value, dict):
        return {
            k: compact_value(v, depth + 1)
            for k, v in value.items()
            if k not in {"vertex_results", "metadata", "tags", "bands", "histogram", "args_schema"}
        }
    if isinstance(value, list):
        return [compact_value(v, depth + 1) for v in value[:12]]
    if isinstance(value, str) and len(value) > COMPACT_MAX_STRING:
        return value[:COMPACT_MAX_STRING] + " [details in node output]"
    return value


def structured_result_text(records: list[dict]) -> str | None:
    """Summarize all data nodes, including later terminal area results.

    Keep complete JSON, never a slice of a manifest from the first node.
    Full raw data remains in the native result pool.
    """
    from terraflow.agentic.services.reusable_flows import node_outputs

    rows = node_outputs(records)
    if not rows:
        return None
    compact = [compact_value(row) for row in rows]
    text = json.dumps(compact, ensure_ascii=False)
    if len(text) <= MAX_RESULT_CHARS:
        return text
    important = {
        "threshold",
        "method",
        "input_transform",
        "direction",
        "output_path",
        "success",
        "passed",
        "reason_code",
        "execution_blocked",
        "water_area_m2",
        "water_fraction",
        "valid_area_m2",
        "valid_pixels",
        "water_pixels",
        "common_valid_pixels",
        "crs",
        "area_method",
        "limitations",
        "flow_id",
        "version",
        "bindings",
        "support",
        "grid_id",
        "transform",
        "shape",
        "source_ids",
        "new_water_area_m2",
        "total_new_water_area_m2",
        "max_new_water_class",
        "classes",
        "excluded_pixels",
        "pixel_area_m2",
        "before",
        "after",
        "change",
        "stats",
        "agreement_area_m2",
        "predicted_only_area_m2",
        "reference_only_area_m2",
        "predicted_water_area_m2",
        "reference_water_area_m2",
        "area_difference_m2",
        "resampling",
        "coverage_bbox_wgs84",
    }
    reduced = [{**row, "outputs": {k: v for k, v in row["outputs"].items() if k in important}} for row in compact]
    text = json.dumps({"node_results": reduced, "details": "Full data in native node outputs"}, ensure_ascii=False)
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return json.dumps(
        {
            "summary_incomplete": True,
            "node_count": len(rows),
            "reason": "Results exceed the assistant summary limit; do not infer missing measurements.",
            "details": "Inspect full data in native node outputs.",
        }
    )


def _get(obj: Any, key: str) -> Any:
    """Read ``key`` from a dict OR an attribute from a pydantic/object."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _as_int(value: Any) -> int:
    """Coerce engine-supplied counts safely; treat junk/None as 0."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def extract_graph_token_usage(graph: Any) -> dict:
    """Sum token usage across every vertex of a *run* graph.

    Token usage is attached to each vertex's ``result.token_usage`` during
    ``finalize_build`` — but only for non-output vertices (an LLM/Agent).
    The engine's ``run_outputs`` contain *only the output vertices*, whose
    ``token_usage`` is ``None`` by design, so the totals must be read by
    walking the graph itself. Pure and dict-shape resilient; never raises.
    """
    input_tokens = output_tokens = total_tokens = 0

    for vertex in _get(graph, "vertices") or []:
        result = _get(vertex, "result")
        if result is None:
            continue
        usage = _get(result, "token_usage")
        if usage is None:
            continue
        input_tokens += _as_int(_get(usage, "input_tokens"))
        output_tokens += _as_int(_get(usage, "output_tokens"))
        total_tokens += _as_int(_get(usage, "total_tokens"))

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _message_to_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        return "\n".join(str(item) for item in message)
    return str(message)


def extract_run_result_text(run_outputs: list[Any]) -> str:
    """Return the flow's user-facing result text, size-capped.

    Prefers ChatOutput messages (what the user sees in the playground);
    falls back to ``results`` when a component produced no message. Returns
    ``"(no output)"`` when the run yielded nothing renderable.
    """
    parts: list[str] = []
    fallback: list[str] = []

    for run_output in run_outputs or []:
        for result_data in _get(run_output, "outputs") or []:
            if result_data is None:
                continue
            messages = _get(result_data, "messages") or []
            for chat_output in messages:
                text = _message_to_text(_get(chat_output, "message"))
                if text:
                    parts.append(text)
            if not messages:
                results = _get(result_data, "results")
                if results:
                    fallback.append(str(results))

    text = "\n".join(parts) if parts else "\n".join(fallback)
    text = text.strip()
    if not text:
        return _NO_OUTPUT
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS]


def _normalize_code(code: str) -> str:
    """Strip per-line trailing whitespace + outer blanks for byte comparison.

    The registry → JSON → flow round-trip occasionally adds or removes trailing
    newlines / mismatched line endings. Normalize before comparing canonical
    code against a node's code so a benign serialization artifact doesn't force
    an unnecessary re-scan (and thus a false-positive on a trusted built-in).
    """
    return "\n".join(line.rstrip() for line in (code or "").splitlines()).strip()


def _get_canonical_code_map() -> dict[str, str]:
    """Return ``{component_type: canonical_code}`` from the loaded registry.

    Used to exempt nodes whose ``code`` field is byte-identical to the
    canonical template provided by the registry — those are trusted built-ins
    the agent added via ``add_component`` (verbatim registry copy).

    Failure modes (registry not loaded, ImportError, downstream exception)
    return an empty dict. Empty dict → the caller scans every node, matching
    the prior behavior. We never trust unverified code on the degraded path.
    """
    try:
        from lfx.mcp.flow_builder_tools._state import _load_registry_user_aware

        registry = _load_registry_user_aware()
    except Exception:  # noqa: BLE001 — defensive: any failure falls back to scan-all
        return {}
    canonical: dict[str, str] = {}
    if not isinstance(registry, dict):
        return canonical
    for component_type, template_dict in registry.items():
        if not isinstance(template_dict, dict):
            continue
        code_field = (template_dict.get("template") or {}).get("code")
        if isinstance(code_field, dict):
            value = code_field.get("value")
            if isinstance(value, str):
                canonical[component_type] = value
    return canonical


def _scan_flow_component_code(payload: dict) -> list[str]:
    """Security-scan every node's inline component ``code`` before run.

    The generation pipeline scans LLM-produced component code, but a flow
    reaching the run engine can carry code that bypassed it (built via
    build_flow with inline code, an overlay ``.components/*.py``, an
    imported flow). The run engine ``exec``s that code, so scan it here
    and refuse to run on any violation. Deterministic, never executes.

    Built-in exemption: when a node's ``code`` is byte-identical (after
    whitespace normalization) to the registry's canonical template for that
    ``type``, skip the scan. Built-ins like ``URLComponent`` legitimately use
    patterns the LLM-generated-code scanner forbids (``importlib.util.find_spec``
    for optional dependency detection, ``os.environ.get`` for proxy env vars).
    Scanning them produces false-positives that block legitimate runs. If the
    code differs from canonical (LLM- or user-modified), it is scanned
    unchanged. Registry-lookup failure falls back to scan-all.
    """
    canonical_code_by_type = _get_canonical_code_map()
    violations: list[str] = []
    for node in (payload or {}).get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        node_data = node.get("data") or {}
        component_type = node_data.get("type") if isinstance(node_data, dict) else None
        template = (node_data.get("node") or {}).get("template") or {}
        code_field = template.get("code")
        code = code_field.get("value") if isinstance(code_field, dict) else None
        if not isinstance(code, str) or not code.strip():
            continue
        canonical = canonical_code_by_type.get(component_type) if isinstance(component_type, str) else None
        if canonical is not None and _normalize_code(code) == _normalize_code(canonical):
            # Trusted built-in: code matches registry verbatim — skip scan.
            continue
        result = scan_code_security(code)
        if not result.is_safe:
            node_id = node.get("id") or node_data.get("id") or "?"
            violations.append(f"{node_id}: {'; '.join(result.violations)}")
    return violations


def extract_vertex_results(graph: Any) -> list[dict]:
    """Serialize actual node results in the native build-pool event shape.

    No second execution and no inference from assistant text. Scientific
    execution_blocked / reason_code are preserved in the tool payload.
    """
    records = []
    for vertex in _get(graph, "vertices") or []:
        result = _get(vertex, "result")
        node_id = _get(vertex, "id")
        if result is None or not node_id:
            continue
        # Native artifacts contain model classes (for port types), which
        # Pydantic JSON mode rejects. Match the native build serializer.
        data = serialize(result)
        if not isinstance(data, dict):
            continue
        data = {**data, "outputs": data.get("outputs") or {}, "logs": data.get("logs") or {}}
        records.append(
            {
                "id": node_id,
                "data": data,
                "valid": True,
                "run_id": str(_get(graph, "run_id") or ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "inactivated_vertices": [],
                "next_vertices_ids": [],
                "top_level_vertices": [],
                "params": {},
                "messages": data.get("messages") or [],
                "artifacts": data.get("artifacts") or {},
            }
        )
    return records


async def run_working_flow(*, flow_data: dict, flow_id: str, user_id: str | None) -> dict:
    """Run the assistant's current canvas flow in-process and return its result.

    Builds a graph from the in-memory canvas data (so unsaved assistant edits
    are honored) and runs it with the current configured component values
    (no input override).

    Returns ``{"result": <text>, "metrics": {...}}`` on success, or
    ``{"error": <message>}`` on failure/timeout — never raises, never leaks
    a stack trace.
    """
    payload = flow_data.get("data") or {}
    flow_name = flow_data.get("name") or "Assistant Flow"

    from terraflow.agentic.services.geo_wiring import geo_wiring_errors

    wiring = geo_wiring_errors(flow_data)
    if wiring:
        return {"error": "Geo wiring error: " + " ".join(wiring)}

    # Security gate: never exec component code that fails the scan, even
    # if it reached the run path without going through generation.
    code_violations = _scan_flow_component_code(payload)
    if code_violations:
        logger.warning("assistant.run_flow.blocked_unsafe_code flow_id=%s n=%d", flow_id, len(code_violations))
        return {"error": f"Refused to run: unsafe component code detected — {'; '.join(code_violations)}"}

    started = perf_counter()
    graph: Any = None
    try:
        graph = await build_graph_from_data(flow_id, payload, flow_name=flow_name, user_id=user_id)
        run_outputs, _session_id = await asyncio.wait_for(
            run_graph_internal(graph, flow_id, inputs=[], outputs=[]),
            timeout=RUN_TIMEOUT_SECONDS,
        )
    except (TimeoutError, asyncio.TimeoutError):
        # On Python 3.10 ``asyncio.wait_for`` raises ``asyncio.TimeoutError``,
        # a class DISTINCT from the builtin ``TimeoutError`` (they were unified
        # in 3.11). Catching only the builtin let 3.10 fall through to the
        # generic handler below, where ``str(asyncio.TimeoutError())`` is ""
        # → an empty error envelope. Catch both so the timeout message is
        # consistent across every supported Python version.
        msg = f"The flow run timed out after {RUN_TIMEOUT_SECONDS}s."
        # Still surface elapsed time + any tokens already billed before the
        # timeout so the agent can report cost/duration, not just "failed".
        timeout_metrics = {
            "duration_seconds": round(perf_counter() - started, 3),
            **extract_graph_token_usage(graph),
        }
        logger.warning(
            "assistant.run_flow.failed flow_id=%s reason=timeout duration_s=%s total_tokens=%s",
            flow_id,
            timeout_metrics["duration_seconds"],
            timeout_metrics["total_tokens"],
        )
        return {"error": msg, "metrics": timeout_metrics}
    except Exception as exc:  # noqa: BLE001 — clean message to the agent, never a stack trace
        raw = str(exc)
        friendly = extract_friendly_error(raw)
        # Log the RAW cause too — the friendly mapping collapses provider
        # errors (e.g. an OpenAI ``The model 'GPT-5.4' does not exist`` vs
        # ``you do not have access to model gpt-5.4``) into one generic
        # "Model not available" string, which hides WHY a run failed. The
        # raw text (truncated; no api keys appear in model errors) is what
        # tells a model-name/casing bug apart from a real access problem.
        logger.warning("assistant.run_flow.failed flow_id=%s friendly=%r raw=%r", flow_id, friendly, raw[:500])
        return {"error": friendly}

    # Wall time measured around the actual run — the only reliable source
    # (ResultData.timedelta is never populated on the returned output
    # vertices, which is why production showed "0,0s"). Token usage is read
    # off the graph's LLM/Agent vertices.
    metrics = {
        "duration_seconds": round(perf_counter() - started, 3),
        **extract_graph_token_usage(graph),
    }
    logger.info(
        "assistant.run_flow.completed flow_id=%s duration_s=%s total_tokens=%s",
        flow_id,
        metrics["duration_seconds"],
        metrics["total_tokens"],
    )
    vertex_results = extract_vertex_results(graph)
    structured = structured_result_text(vertex_results)
    # A chat flow may also produce Data artifacts. Preserve its user-facing
    # answer while giving the assistant scientific measurements from all nodes.
    chat_outputs = [
        {
            "outputs": [
                {"messages": _get(rd, "messages")}
                for rd in _get(ro, "outputs") or []
                if rd is not None and _get(rd, "messages")
            ]
        }
        for ro in run_outputs or []
    ]
    chat_text = extract_run_result_text(chat_outputs)
    text = structured or extract_run_result_text(run_outputs)
    if structured and chat_text != _NO_OUTPUT:
        remaining = max(0, MAX_RESULT_CHARS - len(structured) - 20)
        if remaining:
            text = structured + "\nChat output:\n" + chat_text[:remaining]
    if text == _NO_OUTPUT:
        # The engine's run_outputs only includes chat/output components.
        # A geospatial tool can finish at a Data port with no ChatOutput;
        # report its actual terminal-node data rather than "(no output)".
        sources = {edge.get("source") for edge in payload.get("edges", [])}
        terminal_results = [
            {
                "component_id": record["id"],
                "results": record["data"].get("results"),
                "outputs": record["data"].get("outputs"),
            }
            for record in vertex_results
            if record["id"] not in sources
        ]
        if terminal_results:
            text = json.dumps(terminal_results, ensure_ascii=False)[:MAX_RESULT_CHARS]
    return {
        "result": text,
        "metrics": metrics,
        "vertex_results": vertex_results,
    }
