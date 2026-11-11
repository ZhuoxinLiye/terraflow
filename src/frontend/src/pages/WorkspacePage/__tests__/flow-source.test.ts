import {
  type CanvasIndex,
  describeFlowSource,
  indexByFlowId,
  summarizeFlowSource,
} from "../flow-source";
import type { Scenario } from "../types";

// Synthetic fixtures: ids, names and scenes below are made up for these tests.
const scenarios = [
  {
    id: "water_change",
    title: "水体变化",
    summary: "",
    inputs: [
      { role: "before", label: "前期影像" },
      { role: "after", label: "后期影像" },
    ],
    requirements: [],
    outputs: [],
    tools: [],
    limitations: [],
    examples: [],
  },
] as Scenario[];

const index: CanvasIndex = {
  run_20260101_000000_abc123: {
    flow_id: "flow-run",
    scenario: "water_change",
    scenes: { before: "synthetic.before", after: "synthetic.after" },
    plan: ["raster_viewer.inspect_geotiff", "geo_water.water_evidence"],
    created_at: "2026-01-01T00:00:00+00:00",
  },
  "template:water_change:synthetic.before,synthetic.after": {
    flow_id: "flow-template",
    scenario: "water_change",
    scenes: { before: "synthetic.before", after: "synthetic.after" },
  },
  "template:synthetic_set": { flow_id: "flow-set", input_set: "synthetic_set" },
  run_old: { flow_id: "flow-old", name: "水体分析 · synthetic · run_old" },
};
const byFlowId = indexByFlowId(index);

describe("describeFlowSource", () => {
  it("returns null for a flow the workbench did not generate", () => {
    expect(
      describeFlowSource(
        { id: "flow-native", name: "My agent", tags: [] },
        byFlowId,
        scenarios,
      ),
    ).toBeNull();
  });

  it("describes a run with its scenario, imagery roles and plan", () => {
    const source = describeFlowSource(
      { id: "flow-run", name: "anything" },
      byFlowId,
      scenarios,
    );
    expect(source).toMatchObject({
      kind: "run",
      key: "run_20260101_000000_abc123",
      origin: "运行 run_20260101_000000_abc123",
      scenarioTitle: "水体变化",
      plan: ["inspect_geotiff", "water_evidence"],
    });
    expect(source?.imagery).toEqual([
      { role: "before", label: "前期影像", scene: "synthetic.before" },
      { role: "after", label: "后期影像", scene: "synthetic.after" },
    ]);
    expect(summarizeFlowSource(source!)).toBe(
      "运行 run_20260101_000000_abc123 · 场景 水体变化 · 影像 前期影像 synthetic.before，后期影像 synthetic.after · 步骤 inspect_geotiff → water_evidence · 登记于 2026-01-01",
    );
  });

  it("labels template flows like the old workbench list did", () => {
    const source = describeFlowSource(
      { id: "flow-template" },
      byFlowId,
      scenarios,
    );
    expect(source?.kind).toBe("template");
    expect(source?.origin).toBe("模板 · 水体变化");
    // The scenario is already in the origin, so it is not repeated.
    expect(summarizeFlowSource(source!)).toBe(
      "模板 · 水体变化 · 影像 前期影像 synthetic.before，后期影像 synthetic.after",
    );
  });

  it("falls back to the input set when the entry has no scenario or scenes", () => {
    const source = describeFlowSource({ id: "flow-set" }, byFlowId, scenarios);
    expect(source?.origin).toBe("模板 · synthetic_set");
    expect(source?.imagery).toEqual([
      { role: "input_set", label: "输入组合", scene: "synthetic_set" },
    ]);
  });

  it("does not repeat the word when the input itself is labelled 影像", () => {
    const single = [
      {
        ...scenarios[0],
        id: "water_extent",
        title: "单景水体提取",
        inputs: [{ role: "scene", label: "影像" }],
      },
    ] as Scenario[];
    const source = describeFlowSource(
      { id: "flow-single" },
      indexByFlowId({
        "template:water_extent:synthetic.scene": {
          flow_id: "flow-single",
          scenario: "water_extent",
          scenes: { scene: "synthetic.scene" },
        },
      }),
      single,
    );
    expect(summarizeFlowSource(source!)).toBe(
      "模板 · 单景水体提取 · 影像 synthetic.scene",
    );
  });

  it("says so when an indexed run has no imagery recorded", () => {
    const source = describeFlowSource({ id: "flow-old" }, byFlowId, scenarios);
    expect(summarizeFlowSource(source!)).toBe("运行 run_old · 索引未登记影像");
  });

  it("keeps tagged and legacy-named flows that have no index entry", () => {
    const tagged = describeFlowSource(
      { id: "flow-cli", tags: ["agent-workspace", "water_change"] },
      byFlowId,
      scenarios,
    );
    expect(tagged).toMatchObject({
      kind: "unindexed",
      origin: "命令行生成或索引未登记",
      scenarioTitle: "水体变化",
    });
    expect(summarizeFlowSource(tagged!)).toBe(
      "命令行生成或索引未登记 · 场景 水体变化",
    );
    expect(
      describeFlowSource(
        { id: "flow-legacy", name: "水体分析 · synthetic", tags: null },
        byFlowId,
        scenarios,
      )?.kind,
    ).toBe("unindexed");
  });

  it("does not claim a flow is missing from an index that was not read", () => {
    const source = describeFlowSource(
      { id: "flow-cli", tags: ["agent-workspace"] },
      new Map(),
      [],
      "failed",
    );
    expect(source).toMatchObject({ kind: "unknown", origin: "来源索引未读取" });
    expect(
      describeFlowSource(
        { id: "flow-cli", tags: ["agent-workspace"] },
        new Map(),
        [],
        "loading",
      )?.origin,
    ).toBe("正在读取来源索引…");
  });

  it("shows raw ids when scenario titles are unavailable", () => {
    const source = describeFlowSource({ id: "flow-run" }, byFlowId, []);
    expect(source?.scenarioTitle).toBe("water_change");
    expect(source?.imagery[0]).toEqual({
      role: "before",
      label: "before",
      scene: "synthetic.before",
    });
  });
});
