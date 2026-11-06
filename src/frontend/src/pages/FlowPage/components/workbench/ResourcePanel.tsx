import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Icon from "@/components/common/genericIconComponent";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import useSaveFlow from "@/hooks/flows/use-save-flow";
import { useAddComponent } from "@/hooks/use-add-component";
import { useCatalog, useScenes } from "@/pages/WorkspacePage/api";
import ItemDetail from "@/pages/WorkspacePage/ItemDetail";
import type { CatalogItem } from "@/pages/WorkspacePage/types";
import UploadPanel from "@/pages/WorkspacePage/UploadPanel";
import useAssistantManagerStore from "@/stores/assistantManagerStore";
import useFlowStore from "@/stores/flowStore";
import useFlowsManagerStore from "@/stores/flowsManagerStore";
import { useTypesStore } from "@/stores/typesStore";
import type { APIClassType } from "@/types/api";
import { componentDragData, sceneComponent } from "./resource-components";
import TemplatePanel from "./TemplatePanel";
import DetectionWorkspaceDialog from "./DetectionWorkspaceDialog";

export default function ResourcePanel({
  section,
}: {
  section: "data" | "templates";
}) {
  const save = useSaveFlow();
  const navigate = useNavigate();
  const assistantBusy = useAssistantManagerStore(
    (s) => s.isAssistantProcessing,
  );
  const flowLocked = useFlowStore(
    (s) => s.isBuilding || !!s.currentFlow?.locked,
  );
  if (section === "data") return <DataResourcePanel />;
  return (
    <div
      className="flex h-full min-h-0 flex-col"
      data-testid="workbench-templates"
    >
      <header className="flex h-11 shrink-0 items-center border-b px-3 text-sm font-medium">
        工作流模板
      </header>
      <TemplatePanel
        disabled={flowLocked || assistantBusy}
        save={save}
        openFlow={async (id) => navigate(`/flow/${id}`)}
      />
    </div>
  );
}

function DataResourcePanel() {
  const { items, loading, error, refresh } = useCatalog();
  const { scenes, refresh: refreshScenes } = useScenes();
  const registry = useTypesStore((s) => s.data);
  const add = useAddComponent();
  const assistantBusy = useAssistantManagerStore(
    (s) => s.isAssistantProcessing,
  );
  const flowLocked = useFlowStore(
    (s) => s.isBuilding || !!s.currentFlow?.locked,
  );
  const locked = flowLocked || assistantBusy;
  const [search, setSearch] = useState("");
  const [upload, setUpload] = useState(false);
  const [detail, setDetail] = useState<CatalogItem | null>(null);
  const [developer, setDeveloper] = useState(false);
  const sceneTemplate = Object.values(registry)
    .flatMap(Object.entries)
    .find(([type]) => type === "SceneInput")?.[1];
  const sceneIds = new Set(
    scenes
      .filter(
        (s) => !s.self_check_for && (developer || s.audience !== "developer"),
      )
      .map((s) => s.id),
  );
  const matches = (text: string) =>
    text.toLowerCase().includes(search.toLowerCase());

  function addToCanvas(component: APIClassType, type: string) {
    if (locked) return;
    useFlowsManagerStore.getState().takeSnapshot();
    add(structuredClone(component), type);
  }
  function drag(event: React.DragEvent, component: APIClassType, type: string) {
    if (locked) {
      event.preventDefault();
      return;
    }
    event.dataTransfer.setData(
      "genericNode",
      componentDragData(component, type),
    );
    event.dataTransfer.effectAllowed = "copy";
  }

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="workbench-data">
      <header className="flex h-11 shrink-0 items-center justify-between border-b px-3 text-sm font-medium">
        <span>数据</span>
        <div className="ml-auto mr-1">
          <DetectionWorkspaceDialog />
        </div>
        <Button
          size="icon"
          variant="ghost"
          className="h-7 w-7"
          aria-label="上传数据"
          onClick={() => setUpload(true)}
        >
          <Icon name="Upload" className="h-4 w-4" />
        </Button>
      </header>
      <div className="space-y-2 border-b p-2">
        <Input
          aria-label="搜索数据"
          placeholder="搜索名称、地区或类型"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-8 text-xs"
        />
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={developer}
            onChange={(e) => setDeveloper(e.target.checked)}
          />
          显示工程测试数据
        </label>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2 text-xs">
        {error && (
          <p role="alert" className="p-2 text-destructive">
            {error}
            <Button
              variant="ghost"
              onClick={() => {
                void refresh();
                void refreshScenes();
              }}
            >
              重试
            </Button>
          </p>
        )}
        {loading && <p className="p-2 text-muted-foreground">读取数据目录…</p>}
        {!loading &&
          !error &&
          items.filter(
            (item) =>
              (developer || item.audience !== "developer") &&
              matches(
                `${item.title} ${item.collection_title} ${item.place} ${item.type_label}`,
              ),
          ).length === 0 && (
            <p className="p-2 text-muted-foreground">没有匹配的数据。</p>
          )}
        {items
          .filter(
            (item) =>
              (developer || item.audience !== "developer") &&
              matches(
                `${item.title} ${item.collection_title} ${item.place} ${item.type_label}`,
              ),
          )
          .map((item) => {
            const component = sceneIds.has(item.id)
              ? sceneComponent(sceneTemplate, item.id)
              : null;
            return (
              <div
                key={item.id}
                className="group mb-1 flex items-center gap-2 rounded-md border border-transparent p-1.5 hover:border-border hover:bg-muted/60"
                draggable={!!component && !locked}
                onDragStart={(e) =>
                  component && drag(e, component, "SceneInput")
                }
                data-testid={`resource-${item.id}`}
              >
                <button
                  type="button"
                  onClick={() => setDetail(item)}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  title="查看数据详情"
                >
                  {item.preview ? (
                    <img
                      src={item.preview}
                      alt=""
                      className="h-9 w-10 shrink-0 rounded object-cover"
                    />
                  ) : (
                    <Icon
                      name="FileImage"
                      className="h-9 w-10 shrink-0 p-2 text-muted-foreground"
                    />
                  )}
                  <span className="min-w-0">
                    <span
                      className="block truncate font-medium"
                      title={`${item.collection_title} · ${item.title}`}
                    >
                      {item.title}
                    </span>
                    <span className="block truncate text-[11px] text-muted-foreground">
                      {item.date?.slice(0, 10) || "日期未记录"} ·{" "}
                      {item.type_label}
                    </span>
                    <span className="block truncate text-[10px] text-muted-foreground">
                      {item.collection_title} · {item.origin_label}
                    </span>
                  </span>
                </button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7 shrink-0"
                  aria-label={`将 ${item.title} 加入画布`}
                  disabled={!component || locked}
                  title={
                    component
                      ? "拖入或点击加入当前画布"
                      : "此条目暂未接入原生输入组件，可查看详情"
                  }
                  onClick={() =>
                    component && addToCanvas(component, "SceneInput")
                  }
                >
                  <Icon name="Plus" className="h-3.5 w-3.5" />
                </Button>
              </div>
            );
          })}
      </div>
      <p className="border-t p-2 text-[11px] leading-4 text-muted-foreground">
        拖入或点 + 添加输入节点；在组件与工具中选择工具并连线。
      </p>
      <Dialog open={upload} onOpenChange={setUpload}>
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>上传与登记数据</DialogTitle>
          </DialogHeader>
          <UploadPanel
            onUploaded={async () => {
              await Promise.all([refresh(), refreshScenes()]);
            }}
          />
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!detail}
        onOpenChange={(open) => {
          if (!open) setDetail(null);
        }}
      >
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>数据详情</DialogTitle>
          </DialogHeader>
          {detail && (
            <>
              <img
                src={detail.preview}
                alt={detail.title}
                className="max-h-72 w-full rounded object-contain"
              />
              <ItemDetail item={detail} />
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
