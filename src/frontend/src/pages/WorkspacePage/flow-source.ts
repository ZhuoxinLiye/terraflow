import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { API, apiJson, displayTool } from "./api";
import type { Scenario } from "./types";

/** One entry of the workbench canvas-flow index, keyed by run id or `template:…`. */
export type CanvasIndexEntry = {
  flow_id: string;
  canvas_path?: string;
  name?: string | null;
  input_set?: string | null;
  scenario?: string | null;
  scenes?: Record<string, string> | null;
  plan?: string[] | null;
  created_at?: string;
};

export type CanvasIndex = Record<string, CanvasIndexEntry>;

/** Where a workbench flow came from, as far as the index records it. */
export type WorkbenchFlowSource = {
  kind: "run" | "template" | "unindexed" | "unknown";
  /** Index key; absent when the flow has no index entry. */
  key?: string;
  origin: string;
  scenarioTitle?: string;
  imagery: { role: string; label: string; scene: string }[];
  plan: string[];
  createdAt?: string;
};

export type FlowLike = { id: string; name?: string; tags?: string[] | null };

// Workspace flows carry this tag (see build_water_flow.py); older ones only the name prefix.
export const WORKSPACE_TAG = "agent-workspace";
export const LEGACY_PREFIX = "水体分析";
const TEMPLATE_KEY = "template:";

export function indexByFlowId(index: CanvasIndex) {
  return new Map(
    Object.entries(index).map(([key, entry]) => [
      entry.flow_id,
      { key, entry },
    ]),
  );
}

/**
 * The recorded source of a flow, or null when it did not come from the workbench.
 * `indexState` says whether the index was read, so a missing entry is not reported as
 * "not in the index" while the index is loading or could not be read.
 */
export function describeFlowSource(
  flow: FlowLike,
  byFlowId: ReturnType<typeof indexByFlowId>,
  scenarios: Scenario[],
  indexState: "ready" | "loading" | "failed" = "ready",
): WorkbenchFlowSource | null {
  const indexed = byFlowId.get(flow.id);
  if (
    !indexed &&
    !flow.tags?.includes(WORKSPACE_TAG) &&
    !flow.name?.startsWith(LEGACY_PREFIX)
  )
    return null;

  const scenarioId =
    indexed?.entry.scenario ??
    flow.tags?.find((tag) => scenarios.some((item) => item.id === tag));
  const scenario = scenarios.find((item) => item.id === scenarioId);
  const scenarioTitle = scenario?.title ?? scenarioId ?? undefined;
  if (!indexed)
    return {
      kind: indexState === "ready" ? "unindexed" : "unknown",
      origin:
        indexState === "ready"
          ? "命令行生成或索引未登记"
          : indexState === "loading"
            ? "正在读取来源索引…"
            : "来源索引未读取",
      scenarioTitle,
      imagery: [],
      plan: [],
    };

  const { key, entry } = indexed;
  const isTemplate = key.startsWith(TEMPLATE_KEY);
  const imagery = Object.entries(entry.scenes ?? {}).map(([role, scene]) => ({
    role,
    label: scenario?.inputs.find((input) => input.role === role)?.label ?? role,
    scene,
  }));
  if (!imagery.length && entry.input_set)
    imagery.push({
      role: "input_set",
      label: "输入组合",
      scene: entry.input_set,
    });
  return {
    kind: isTemplate ? "template" : "run",
    key,
    origin: isTemplate
      ? "模板 · " +
        (scenarioTitle ?? entry.input_set ?? key.slice(TEMPLATE_KEY.length))
      : "运行 " + key,
    scenarioTitle,
    imagery,
    plan: (entry.plan ?? []).map(displayTool),
    createdAt: entry.created_at,
  };
}

/** One line for the workflow list; the same text is the row's tooltip. */
export function summarizeFlowSource(source: WorkbenchFlowSource) {
  const parts = [source.origin];
  if (source.scenarioTitle && !source.origin.includes(source.scenarioTitle))
    parts.push("场景 " + source.scenarioTitle);
  if (source.imagery.length)
    parts.push(
      "影像 " +
        source.imagery
          .map((item) =>
            // A single-input scenario labels its input "影像" as well.
            item.label === "影像" ? item.scene : item.label + " " + item.scene,
          )
          .join("，"),
    );
  else if (source.kind === "run" || source.kind === "template")
    parts.push("索引未登记影像");
  if (source.plan.length) parts.push("步骤 " + source.plan.join(" → "));
  if (source.createdAt) parts.push("登记于 " + source.createdAt.slice(0, 10));
  return parts.join(" · ");
}

/** The workbench index and scenario titles, read once and shared by every list row. */
export function useWorkbenchFlowSources(enabled = true) {
  const index = useQuery({
    queryKey: ["workbenchCanvasIndex"],
    queryFn: async () =>
      (await apiJson<{ flows?: CanvasIndex }>(API + "/canvas-flows")).flows ??
      {},
    enabled,
    retry: 1,
    refetchOnWindowFocus: false,
  });
  // Titles and input labels only; the list still shows raw ids when this request fails.
  const scenarios = useQuery({
    queryKey: ["workbenchScenarios"],
    queryFn: async () =>
      (await apiJson<{ scenarios: Scenario[] }>(API + "/scenarios")).scenarios,
    enabled,
    retry: 1,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
  const byFlowId = useMemo(() => indexByFlowId(index.data ?? {}), [index.data]);
  const state = index.isSuccess
    ? "ready"
    : index.isError
      ? "failed"
      : "loading";
  const scenarioList = scenarios.data;
  const sourceOf = useCallback(
    (flow: FlowLike) =>
      describeFlowSource(flow, byFlowId, scenarioList ?? [], state),
    [byFlowId, scenarioList, state],
  );
  return { error: index.isError, sourceOf };
}
