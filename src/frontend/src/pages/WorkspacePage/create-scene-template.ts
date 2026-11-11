import { API, apiFetch, postJson } from "./api";

type TemplateResponse = { flow_id?: string; status?: string; error?: string };

/**
 * `stale`: the workbench index names a template flow for these inputs, but that flow no
 * longer exists in Terraflow. Nothing was created and the index was left as it is.
 */
export type SceneTemplateResult = {
  status: "created" | "exists" | "stale";
  flowId: string;
};

async function requestTemplate(
  scenario: string,
  inputs: Record<string, string>,
): Promise<SceneTemplateResult> {
  const response = await postJson(API + "/canvas-templates", {
    scenario,
    inputs,
  });
  const body = (await response.json()) as TemplateResponse;
  if (!response.ok)
    throw new Error(
      body.error || "模板创建失败（HTTP " + response.status + "）。",
    );
  if (!body.flow_id) throw new Error("服务未返回工作流编号。");
  return {
    status: body.status === "exists" ? "exists" : "created",
    flowId: body.flow_id,
  };
}

/**
 * The one place that asks the workbench service for a remote-sensing template flow.
 * The service answers "exists" from its index even after that flow was deleted; the index
 * entry is only dropped when the caller passes `replaceStale` (an explicit user choice).
 */
export async function createSceneTemplate(
  scenario: string,
  inputs: Record<string, string>,
  { replaceStale = false }: { replaceStale?: boolean } = {},
): Promise<SceneTemplateResult> {
  const result = await requestTemplate(scenario, inputs);
  if (result.status !== "exists") return result;
  const flow = await apiFetch("/api/v1/flows/" + result.flowId);
  if (flow.status !== 404) return result;
  if (!replaceStale) return { status: "stale", flowId: result.flowId };
  const forgotten = await apiFetch(
    API + "/canvas-flows/" + encodeURIComponent(result.flowId),
    { method: "DELETE" },
  );
  if (!forgotten.ok)
    throw new Error("无法清除旧索引记录（HTTP " + forgotten.status + "）。");
  return requestTemplate(scenario, inputs);
}
