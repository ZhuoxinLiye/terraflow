import { useEffect, useRef, useState } from "react";
import Icon from "@/components/common/genericIconComponent";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { useAddComponent } from "@/hooks/use-add-component";
import useAssistantManagerStore from "@/stores/assistantManagerStore";
import useFlowStore from "@/stores/flowStore";
import useFlowsManagerStore from "@/stores/flowsManagerStore";
import { useTypesStore } from "@/stores/typesStore";

type Selection = {
  dataset_id: string;
  snapshot_id: string;
  detection_count: number;
};

export default function DetectionWorkspaceDialog() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [selection, setSelection] = useState<Selection | null>(null);
  const frame = useRef<HTMLIFrameElement>(null);
  const add = useAddComponent();
  const registry = useTypesStore((s) => s.data);
  const assistantBusy = useAssistantManagerStore(
    (s) => s.isAssistantProcessing,
  );
  const flowLocked = useFlowStore(
    (s) => s.isBuilding || !!s.currentFlow?.locked,
  );
  const entry = Object.values(registry)
    .flatMap(Object.entries)
    .find(
      ([type, component]) =>
        type === "TerraboxGraphQueryQueryNodes" &&
        component.template?.dataset_id &&
        component.template?.target_type_contains &&
        component.template?.limit,
    );

  useEffect(() => {
    function receive(event: MessageEvent) {
      if (
        event.origin !== window.location.origin ||
        event.source !== frame.current?.contentWindow
      )
        return;
      if (event.data?.type === "earthmind:detection-busy")
        setBusy(event.data.busy === true);
      if (event.data?.type === "earthmind:detection-cleared")
        setSelection(null);
      if (
        event.data?.type === "earthmind:detection-selected" &&
        /^segearth:[a-f0-9]{32}$/.test(event.data.dataset_id) &&
        /^sha256:[a-f0-9]{64}$/.test(event.data.snapshot_id) &&
        Number.isInteger(event.data.detection_count) &&
        event.data.detection_count >= 0
      ) {
        setSelection(event.data);
      }
    }
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, []);

  function addQuery() {
    if (!entry || !selection || flowLocked || assistantBusy) return;
    const [type, original] = entry;
    const component = structuredClone(original);
    const values = {
      dataset_id: selection.dataset_id,
      snapshot_id: selection.snapshot_id,
      partition_id: "IMAGE",
      node_type: "target",
      limit: 20,
      facility_id: "",
      target_type_contains: "",
      risk_level: "",
    };
    for (const [name, value] of Object.entries(values)) {
      if (component.template[name]) component.template[name].value = value;
    }
    useFlowsManagerStore.getState().takeSnapshot();
    add(component, type);
    setOpen(false);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!busy) setOpen(next);
      }}
    >
      <Button
        size="sm"
        variant="outline"
        className="h-7 gap-1 text-xs"
        onClick={() => {
          setSelection(null);
          setOpen(true);
        }}
        aria-label="检测与标注"
      >
        <Icon name="ScanSearch" className="h-3.5 w-3.5" />
        检测
      </Button>
      <DialogContent
        className="flex h-[94vh] w-[96vw] max-w-none flex-col gap-2 p-3"
        data-testid="detection-workspace"
      >
        <DialogHeader className="pr-8">
          <DialogTitle>检测与标注</DialogTitle>
          <DialogDescription>
            导入影像运行检测，或查看已保存结果。选择结果后可添加同一快照的图谱查询节点。
          </DialogDescription>
        </DialogHeader>
        <div
          className="flex min-h-8 items-center gap-3 text-xs"
          aria-live="polite"
        >
          {busy ? (
            <span>正在检测，请等待本次任务结束。</span>
          ) : selection ? (
            <span>
              已选择 {selection.detection_count} 个模型候选区域 ·{" "}
              {selection.dataset_id}
            </span>
          ) : (
            <span>在预览中点击“用于图谱查询”选择结果。</span>
          )}
          <Button
            size="sm"
            className="ml-auto h-7 text-xs"
            disabled={
              !selection || !entry || busy || flowLocked || assistantBusy
            }
            onClick={addQuery}
          >
            添加图谱计数节点
          </Button>
        </div>
        <iframe
          ref={frame}
          src="/api/workspace/detection/ui"
          title="SegEarth 检测与结果预览"
          className="min-h-0 w-full flex-1 rounded border bg-white"
          allow="fullscreen"
        />
      </DialogContent>
    </Dialog>
  );
}
