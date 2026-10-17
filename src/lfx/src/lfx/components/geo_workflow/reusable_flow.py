"""Invoke an approved flow snapshot with fresh catalog inputs."""

import json

from lfx.custom import Component
from lfx.io import DataInput, MessageTextInput, MultilineInput, Output
from lfx.schema.data import Data


class ReusableFlowComponent(Component):
    display_name = "可复用流程"
    description = "Run an approved reusable flow version. Discover IDs and contracts with search_reusable_flows."
    name = "ReusableFlow"
    icon = "Workflow"
    inputs = [
        DataInput(
            name="preconditions",
            display_name="Preflight result",
            required=False,
            info="Optional upstream scientific gate. Failed/blocked results prevent child execution.",
        ),
        MessageTextInput(name="asset_id", display_name="Flow ID", required=True),
        MessageTextInput(name="version", display_name="Version", required=True),
        MultilineInput(name="bindings", display_name="Input bindings (JSON)", value='{"scene_id": ""}', required=True),
    ]
    outputs = [Output(name="result", display_name="Result and evidence", method="invoke")]

    async def invoke(self) -> Data:
        from terraflow.agentic.services.reusable_flows import execute_reusable_flow

        gate = self.preconditions
        if gate is not None:
            # Terrabox's native Data port returns list[Data], including for
            # a single result. Check every supplied gate, not just the first.
            gates = gate if isinstance(gate, list) else [gate]
            if not gates:
                message = "preconditions_missing"
                raise ValueError(message)
            for item in gates:
                raw = item.data if isinstance(item, Data) else item
                if not isinstance(raw, dict):
                    message = "preconditions_invalid"
                    raise TypeError(message)
                outputs = raw.get("outputs") or raw
                if (
                    raw.get("success") is False
                    or outputs.get("passed") is False
                    or outputs.get("success") is False
                    or outputs.get("execution_blocked")
                ):
                    message = "preconditions_failed"
                    raise ValueError(message)
        bindings = json.loads(self.bindings)
        if not isinstance(bindings, dict):
            message = "Input bindings must be a JSON object"
            raise TypeError(message)
        # Graph.user_id is set by the authenticated engine, never by the model.
        result = await execute_reusable_flow(
            user_id=str(self.user_id), flow_id=self.asset_id, version=self.version, bindings=bindings
        )
        self.status = {"flow_id": self.asset_id, "version": self.version, "success": result["success"]}
        return Data(data=result)
