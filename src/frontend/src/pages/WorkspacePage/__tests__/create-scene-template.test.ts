import { createSceneTemplate } from "../create-scene-template";

// Synthetic responses; no workbench service or Terraflow backend is contacted.
type Call = { url: string; method: string; body?: unknown };

function mockFetch(answers: Array<{ status: number; body?: unknown }>): Call[] {
  const calls: Call[] = [];
  const queue = [...answers];
  global.fetch = jest.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({
      url,
      method: init.method ?? "GET",
      body: init.body ? JSON.parse(String(init.body)) : undefined,
    });
    const answer = queue.shift();
    if (!answer) throw new Error("unexpected request " + url);
    return {
      ok: answer.status < 400,
      status: answer.status,
      json: async () => answer.body ?? {},
    };
  }) as unknown as typeof fetch;
  return calls;
}

const inputs = { before: "synthetic.before", after: "synthetic.after" };

describe("createSceneTemplate", () => {
  it("creates a template flow with one request", async () => {
    const calls = mockFetch([
      { status: 201, body: { status: "created", flow_id: "new-flow" } },
    ]);
    await expect(createSceneTemplate("water_change", inputs)).resolves.toEqual({
      status: "created",
      flowId: "new-flow",
    });
    expect(calls).toEqual([
      {
        url: "/api/workspace/canvas-templates",
        method: "POST",
        body: { scenario: "water_change", inputs },
      },
    ]);
  });

  it("returns the existing flow when the index entry is still valid", async () => {
    const calls = mockFetch([
      { status: 200, body: { status: "exists", flow_id: "old-flow" } },
      { status: 200, body: { id: "old-flow" } },
    ]);
    await expect(createSceneTemplate("water_change", inputs)).resolves.toEqual({
      status: "exists",
      flowId: "old-flow",
    });
    expect(calls.map((call) => call.method + " " + call.url)).toEqual([
      "POST /api/workspace/canvas-templates",
      "GET /api/v1/flows/old-flow",
    ]);
  });

  it("reports a deleted flow without touching the index", async () => {
    const calls = mockFetch([
      { status: 200, body: { status: "exists", flow_id: "gone-flow" } },
      { status: 404 },
    ]);
    await expect(createSceneTemplate("water_change", inputs)).resolves.toEqual({
      status: "stale",
      flowId: "gone-flow",
    });
    expect(calls.map((call) => call.method)).toEqual(["POST", "GET"]);
  });

  it("drops the stale entry and creates again only when asked to", async () => {
    const calls = mockFetch([
      { status: 200, body: { status: "exists", flow_id: "gone-flow" } },
      { status: 404 },
      { status: 200, body: { status: "ok", removed: 1 } },
      { status: 201, body: { status: "created", flow_id: "new-flow" } },
    ]);
    await expect(
      createSceneTemplate("water_change", inputs, { replaceStale: true }),
    ).resolves.toEqual({ status: "created", flowId: "new-flow" });
    expect(calls.map((call) => call.method + " " + call.url)).toEqual([
      "POST /api/workspace/canvas-templates",
      "GET /api/v1/flows/gone-flow",
      "DELETE /api/workspace/canvas-flows/gone-flow",
      "POST /api/workspace/canvas-templates",
    ]);
  });

  it("keeps the index when the flow lookup fails for another reason", async () => {
    const calls = mockFetch([
      { status: 200, body: { status: "exists", flow_id: "old-flow" } },
      { status: 502 },
    ]);
    await expect(
      createSceneTemplate("water_change", inputs, { replaceStale: true }),
    ).resolves.toEqual({ status: "exists", flowId: "old-flow" });
    expect(calls).toHaveLength(2);
  });

  it("surfaces the service's own error message", async () => {
    mockFetch([{ status: 400, body: { error: "两景影像不能相同。" } }]);
    await expect(createSceneTemplate("water_change", inputs)).rejects.toThrow(
      "两景影像不能相同。",
    );
  });

  it("fails when the service returns no flow id", async () => {
    mockFetch([{ status: 201, body: { status: "created" } }]);
    await expect(createSceneTemplate("water_change", inputs)).rejects.toThrow(
      "服务未返回工作流编号。",
    );
  });
});
