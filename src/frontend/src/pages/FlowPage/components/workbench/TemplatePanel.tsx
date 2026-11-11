import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  API,
  apiJson,
  pickableScenes,
  useScenes,
} from "@/pages/WorkspacePage/api";
import { createSceneTemplate } from "@/pages/WorkspacePage/create-scene-template";
import type { Scenario } from "@/pages/WorkspacePage/types";

/**
 * The remote-sensing template form: pick a task and its imagery, open the template flow.
 * Mounted by the canvas sidebar and by the shared template directory; both create through
 * `createSceneTemplate`.
 */
export default function TemplatePanel({
  disabled,
  save,
  openFlow,
  submitLabel = "保存当前图并打开模板",
  intro = "选择影像，打开由原生组件组成的模板。当前工作流先保存，模板在新工作流中打开。",
}: {
  disabled: boolean;
  /** Saves the flow being edited, if any, before the template opens in another flow. */
  save: () => Promise<void>;
  openFlow: (id: string) => Promise<void>;
  submitLabel?: string;
  intro?: string;
}) {
  const { scenes } = useScenes();
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selected, setSelected] = useState("");
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
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
  async function create(replaceStale = false) {
    if (!scenario || !ready || busy || disabled) return;
    setBusy(true);
    setError("");
    setStale(false);
    try {
      await save();
      const result = await createSceneTemplate(
        scenario.id,
        Object.fromEntries(
          scenario.inputs.map((input) => [input.role, roles[input.role]]),
        ),
        { replaceStale },
      );
      if (result.status === "stale") {
        setStale(true);
        setError(
          "索引中登记的这个模板工作流已被删除，旧记录仍在，所以没有生成新的。",
        );
        return;
      }
      await openFlow(result.flowId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "模板创建失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-3 overflow-y-auto p-3 text-xs">
      <p className="leading-5 text-muted-foreground">{intro}</p>
      <label className="block space-y-1">
        <span>分析任务</span>
        <select
          aria-label="分析任务"
          className="h-8 w-full rounded-md border bg-background px-2"
          value={selected}
          onChange={(e) => {
            setSelected(e.target.value);
            setRoles({});
            setError("");
            setStale(false);
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
        {busy ? "正在打开…" : submitLabel}
      </Button>
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
      {stale && (
        <Button
          size="sm"
          variant="outline"
          className="w-full"
          disabled={busy || disabled}
          onClick={() => void create(true)}
        >
          清除这条旧记录并重新生成
        </Button>
      )}
    </div>
  );
}
