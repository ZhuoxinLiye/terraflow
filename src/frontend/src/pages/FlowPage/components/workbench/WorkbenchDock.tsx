import { useEffect } from "react";
import Icon from "@/components/common/genericIconComponent";
import { AssistantPanel } from "@/components/core/assistantPanel";
import { Button } from "@/components/ui/button";
import { useSidebar } from "@/components/ui/sidebar";
import useAssistantManagerStore from "@/stores/assistantManagerStore";
import useFlowStore from "@/stores/flowStore";
import InspectionPanel from "../InspectionPanel";

export default function WorkbenchDock() {
  const assistantOpen = useAssistantManagerStore((s) => s.assistantSidebarOpen);
  const setAssistantOpen = useAssistantManagerStore(
    (s) => s.setAssistantSidebarOpen,
  );
  const nodes = useFlowStore((s) => s.nodes);
  const inspection = useFlowStore((s) => s.inspectionPanelVisible);
  const setInspection = useFlowStore((s) => s.setInspectionPanelVisible);
  const selected = nodes.filter((n) => n.selected);
  const node =
    selected.length === 1 && selected[0].type === "genericNode"
      ? selected[0]
      : null;
  const { open, setOpen } = useSidebar();
  const visible = assistantOpen || (!!node && inspection);

  // A deliberate new node selection switches to its existing property editor.
  // Keep the assistant instance mounted so closing/toggling preserves its stream.
  useEffect(() => {
    if (node && inspection) setAssistantOpen(false);
  }, [node?.id]);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 1199px)");
    const sync = () => {
      if (visible && media.matches) setOpen(false);
    };
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, [visible, setOpen]);
  useEffect(() => {
    if (open && window.innerWidth < 1200) {
      setAssistantOpen(false);
      if (inspection) setInspection(false);
    }
  }, [open, setAssistantOpen, setInspection]);

  return (
    <aside
      className="workbench-dock noflow"
      hidden={!visible}
      data-testid="workbench-dock"
    >
      <div className="flex h-9 shrink-0 items-center gap-1 border-b px-2 text-xs">
        <Button
          size="sm"
          variant={assistantOpen ? "secondary" : "ghost"}
          className="h-7 text-xs"
          onClick={() => setAssistantOpen(true)}
        >
          工作流助手
        </Button>
        {node && (
          <Button
            size="sm"
            variant={!assistantOpen ? "secondary" : "ghost"}
            className="h-7 text-xs"
            onClick={() => {
              setInspection(true);
              setAssistantOpen(false);
            }}
          >
            节点属性
          </Button>
        )}
        <Button
          size="icon"
          variant="ghost"
          className="ml-auto h-7 w-7"
          aria-label="关闭右侧面板"
          onClick={() => {
            setAssistantOpen(false);
            setInspection(false);
          }}
        >
          <Icon name="X" className="h-3.5 w-3.5" />
        </Button>
      </div>
      <div className="min-h-0 flex-1" hidden={!assistantOpen}>
        <AssistantPanel
          docked
          isOpen={assistantOpen}
          onClose={() => setAssistantOpen(false)}
        />
      </div>
      {!assistantOpen && node && inspection && (
        <InspectionPanel docked selectedNode={node} />
      )}
    </aside>
  );
}
