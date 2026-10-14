import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  API,
  apiJson,
  pickableScenes,
  useScenes,
} from "@/pages/WorkspacePage/api";
import type { Scenario } from "@/pages/WorkspacePage/types";

export default function TemplatePanel({
  disabled,
  save,
  openFlow,
}: {
  disabled: boolean;
  save: () => Promise<void>;
  openFlow: (id: string) => Promise<void>;
}) {
  const { scenes } = useScenes();
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selected, setSelected] = useState("");
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const scenario = scenarios.find((s) => s.id === selected);
  const choices = pickableScenes(scenes, false).filter((s) =>
    scenario?.input_kinds?.includes(s.input_kind),
  );
  const ready =
    scenario?.inputs.every((input) => roles[input.role]) &&
    new Set(Object.values(roles)).size === Object.keys(roles).length;
  useEffect(() => {
    void apiJson<{ scenarios: Scenario[] }>(API + "/scenarios")
      .then((body) =>
        setScenarios(body.scenarios.filter((s) => s.canvas_template)),
      )
      .catch((e) => setError(String(e)));
  }, []);
  async function create() {
    if (!ready || busy || disabled) return;
    setBusy(true);
    setError("");
    try {
      await save();
      const result = await apiJson<{ flow_id: string }>(
        API + "/canvas-templates",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ scenario: selected, inputs: roles }),
        },
      );
      if (!result.flow_id) throw new Error("服务未返回工作流编号。");
      await openFlow(result.flow_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "模板创建失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-3 overflow-y-auto p-3 text-xs">
      <p className="leading-5 text-muted-foreground">
        选择影像，打开由原生组件组成的模板。当前工作流先保存，模板在新工作流中打开。
      </p>
      <label className="block space-y-1">
        <span>分析任务</span>
        <select
          aria-label="分析任务"
          className="h-8 w-full rounded-md border bg-background px-2"
          value={selected}
          onChange={(e) => {
            setSelected(e.target.value);
            setRoles({});
          }}
        >
          <option value="">选择模板</option>
          {scenarios.map((s) => (
            <option key={s.id} value={s.id}>
              {s.title}
            </option>
          ))}
        </select>
      </label>
      {scenario?.inputs.map((input) => (
        <label key={input.role} className="block space-y-1">
          <span>{input.label}</span>
          <select
            aria-label={input.label}
            className="h-8 w-full rounded-md border bg-background px-2"
            value={roles[input.role] || ""}
            onChange={(e) =>
              setRoles((r) => ({ ...r, [input.role]: e.target.value }))
            }
          >
            <option value="">选择影像</option>
            {choices.map((s) => (
              <option key={s.id} value={s.id}>
                {s.collection_title} · {s.title}
              </option>
            ))}
          </select>
        </label>
      ))}
      {scenario && (
        <p className="leading-5 text-muted-foreground">{scenario.summary}</p>
      )}
      <Button
        size="sm"
        className="w-full"
        disabled={!ready || busy || disabled}
        onClick={() => void create()}
      >
        {busy ? "正在打开…" : "保存当前图并打开模板"}
      </Button>
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
