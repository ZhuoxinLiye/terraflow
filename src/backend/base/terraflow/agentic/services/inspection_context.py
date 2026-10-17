"""Request-local capability boundary for read-only assistant turns."""

from contextvars import ContextVar

inspection_only: ContextVar[bool] = ContextVar("assistant_inspection_only", default=False)

READ_TOOL_NAMES = frozenset(
    {"search_components", "describe_component", "describe_flow_io", "get_field_value", "search_remote_sensing_data",
     "search_reusable_flows"}
)
