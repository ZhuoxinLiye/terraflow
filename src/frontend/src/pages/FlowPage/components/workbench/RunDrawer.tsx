import { useState } from "react";
import SwitchOutputView from "@/CustomNodes/GenericNode/components/outputModal/components/switchOutputView";
import { Button } from "@/components/ui/button";
import useFlowStore from "@/stores/flowStore";
import { refusalReason } from "./run-evidence";

/** Only reads the native build pool: no second runner or inferred success. */
export default function RunDrawer() {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"outputs" | "logs">("outputs");
  const pool = useFlowStore((s) => s.flowPool);
  const nodes = useFlowStore((s) => s.nodes);
  const building = useFlowStore((s) => s.isBuilding);
  const flowId = useFlowStore((s) => s.currentFlow?.id);
  const fitNode = useFlowStore((s) => s.fitViewNode);
  const entries = Object.entries(pool).flatMap(([nodeId, runs]) =>
    runs.map((run, i) => ({
      nodeId,
      run,
      index: i,
      refusal: refusalReason(run.data),
    })),
  );
  const failed = entries.filter(
    ({ run, refusal }) => !run.valid || refusal,
  ).length;
  return (
    <section
      className="workbench-results noflow"
      data-testid="workbench-results"
    >
      <div className="flex h-8 items-center gap-2 border-t bg-background px-3 text-xs">
        <button
          type="button"
          className="flex h-full items-center gap-2"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <span>{open ? "⌄" : "⌃"}</span>
          <span>结果与日志</span>
          <span
            className={failed ? "text-destructive" : "text-muted-foreground"}
          >
            {building
              ? "运行中…"
              : entries.length
                ? `${entries.length} 条节点记录${failed ? ` · ${failed} 条失败/拒绝` : ""}`
                : "尚未运行"}
          </span>
        </button>
        <span className="ml-auto truncate text-[10px] text-muted-foreground">
          当前工作流 · {flowId?.slice(0, 8)}
        </span>
      </div>
      {open && (
        <div className="flex h-56 min-h-0 flex-col border-t bg-background">
          <div className="flex h-8 shrink-0 items-center gap-1 border-b px-2">
            {(["outputs", "logs"] as const).map((key) => (
              <Button
                key={key}
                size="sm"
                variant={tab === key ? "secondary" : "ghost"}
                className="h-6 text-xs"
                onClick={() => setTab(key)}
              >
                {key === "outputs" ? "节点输出" : "节点日志"}
              </Button>
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-auto p-2 text-xs">
            {!entries.length && (
              <p className="p-2 text-muted-foreground">
                使用画布的运行按钮执行当前工作流。节点输出与拒绝原因会显示在这里。
              </p>
            )}
            {entries.map(({ nodeId, run, index, refusal }) => (
              <details
                key={`${nodeId}-${index}`}
                className="mb-1 rounded border"
                open={!run.valid || !!refusal}
              >
                <summary className="cursor-pointer px-2 py-1.5">
                  <span
                    className={!run.valid || refusal ? "text-destructive" : ""}
                  >
                    {nodes.find((n) => n.id === nodeId)?.data.node
                      ?.display_name || nodeId}{" "}
                    ·{" "}
                    {refusal
                      ? "科学检查拒绝"
                      : run.valid
                        ? "已返回"
                        : "失败 / 拒绝"}
                  </span>
                  <span className="ml-2 text-[10px] text-muted-foreground">
                    {run.run_id || ""}
                  </span>
                </summary>
                <div className="border-t p-2">
                  {refusal && (
                    <p role="alert" className="mb-2 text-destructive">
                      {refusal}
                    </p>
                  )}
                  <Button
                    size="sm"
                    variant="ghost"
                    className="mb-1 h-6 text-xs"
                    onClick={() => fitNode(nodeId)}
                  >
                    定位节点
                  </Button>
                  {tab === "outputs" &&
                    index === (pool[nodeId]?.length ?? 0) - 1 &&
                    Object.keys(run.data?.outputs ?? {}).map((name) => (
                      <div className="my-2 rounded border p-2" key={name}>
                        <p className="mb-1 font-medium">{name}</p>
                        <SwitchOutputView
                          nodeId={nodeId}
                          outputName={name}
                          type="Outputs"
                        />
                      </div>
                    ))}
                  <details>
                    <summary className="cursor-pointer text-muted-foreground">
                      原始{tab === "logs" ? "日志" : "输出与证据"}
                    </summary>
                    <pre className="whitespace-pre-wrap break-all text-[11px] leading-5">
                      {JSON.stringify(
                        tab === "logs"
                          ? run.data?.logs
                          : {
                              results: run.data?.results,
                              outputs: run.data?.outputs,
                              artifacts: run.artifacts,
                            },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                </div>
              </details>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
