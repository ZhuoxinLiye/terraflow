import { useState } from "react";
import Icon from "@/components/common/genericIconComponent";
import { Button } from "@/components/ui/button";
import useSaveFlow from "@/hooks/flows/use-save-flow";
import useAlertStore from "@/stores/alertStore";
import useAssistantManagerStore from "@/stores/assistantManagerStore";
import useFlowStore from "@/stores/flowStore";
import DeployButton from "./deploy-button";
import PublishDropdown from "./deploy-dropdown";
import PlaygroundButton from "./playground-button";

type FlowToolbarOptionsProps = {
  openApiModal: boolean;
  setOpenApiModal: (open: boolean | ((prev: boolean) => boolean)) => void;
};
const FlowToolbarOptions = ({
  openApiModal,
  setOpenApiModal,
}: FlowToolbarOptionsProps) => {
  const hasIO = useFlowStore((state) => state.hasIO);
  const building = useFlowStore((state) => state.isBuilding);
  const locked = useFlowStore(
    (state) => !!state.currentFlow?.locked || state.nodes.length === 0,
  );
  const processing = useAssistantManagerStore(
    (state) => state.isAssistantProcessing,
  );
  const saveFlow = useSaveFlow();
  const [saving, setSaving] = useState(false);
  async function runCurrentFlow() {
    if (building) {
      useFlowStore.getState().stopBuilding();
      return;
    }
    if (saving || processing || locked) return;
    setSaving(true);
    try {
      await saveFlow();
      await useFlowStore.getState().buildFlow({});
    } catch (error) {
      useAlertStore.getState().setErrorData({
        title: "运行失败",
        list: [error instanceof Error ? error.message : String(error)],
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex items-center gap-1">
      <Button
        data-testid="workbench-run"
        size="sm"
        className="h-8 gap-1.5"
        disabled={!building && (saving || processing || locked)}
        onClick={() => void runCurrentFlow()}
      >
        <Icon name={building ? "Square" : "Play"} className="h-3.5 w-3.5" />
        {building ? "停止" : saving ? "保存中…" : "运行"}
      </Button>
      <Button
        size="icon"
        variant="ghost"
        className="h-8 w-8"
        aria-label="打开工作流助手"
        onClick={() => {
          const store = useAssistantManagerStore.getState();
          store.setAssistantSidebarOpen(!store.assistantSidebarOpen);
        }}
      >
        <Icon name="Sparkles" className="h-4 w-4" />
      </Button>
      {hasIO && <PlaygroundButton hasIO={hasIO} />}
      <PublishDropdown
        openApiModal={openApiModal}
        setOpenApiModal={setOpenApiModal}
      />
      <DeployButton />
    </div>
  );
};

export default FlowToolbarOptions;
