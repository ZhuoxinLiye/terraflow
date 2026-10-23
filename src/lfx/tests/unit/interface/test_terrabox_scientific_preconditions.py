"""Synthetic gate results; exercise the generated component's actual execute method."""

import ast
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from lfx.interface.earthflow_terrabox import (
    TerraboxToolSpec,
    build_terrabox_component_source,
    scientific_precondition_error,
)
from lfx.schema.data import Data


@pytest.mark.parametrize(
    "payload",
    [
        {"success": True, "outputs": {"execution_blocked": True, "reason_code": "shape_mismatch"}},
        {"success": True, "outputs": {"success": False}},
        {},
        [],
        [Data(data={"outputs": {"passed": True}}), Data(data={"outputs": {"execution_blocked": True}})],
    ],
)
def test_blocked_or_unavailable_prerequisite_is_refused(payload):
    assert scientific_precondition_error(payload)


@pytest.mark.parametrize(
    "payload",
    [None, {"outputs": {"success": True, "execution_blocked": False}}, Data(data={"outputs": {"passed": True}})],
)
def test_successful_gate_or_unconnected_optional_input(payload):
    assert scientific_precondition_error(payload) is None


def test_generated_execute_does_not_call_http_for_failed_preflight():
    spec = TerraboxToolSpec("geo_water.water_by_class", "Class", "", {"type": "object", "properties": {}})
    source = ast.parse(build_terrabox_component_source(spec))
    cls = next(n for n in source.body if isinstance(n, ast.ClassDef))
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_execute")
    namespace = {"Any": object, "scientific_precondition_error": scientific_precondition_error}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<generated-execute>", "exec"), namespace)  # noqa: S102 - execute only locally generated canonical test code
    component = SimpleNamespace(
        preconditions=Data(
            data={"success": True, "outputs": {"execution_blocked": True, "reason_code": "shape_mismatch"}}
        ),
        _TERRABOX_SLUG=spec.slug,
    )
    with patch("requests.post") as post:
        result = namespace["_execute"](component, {})
    post.assert_not_called()
    assert result["outputs"]["reason_code"] == "shape_mismatch"
