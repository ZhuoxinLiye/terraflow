import { useParams } from "react-router-dom";
import useSaveFlow from "@/hooks/flows/use-save-flow";
import TemplatePanel from "@/pages/FlowPage/components/workbench/TemplatePanel";
import { useOpenWorkbenchFlow } from "@/pages/WorkspacePage/use-open-workbench-flow";
import useAssistantManagerStore from "@/stores/assistantManagerStore";
import useFlowStore from "@/stores/flowStore";

/**
 * The remote-sensing category of the template directory. It mounts the same form as the
 * canvas sidebar, so there is one implementation of the scenario/imagery choice and of
 * the request that creates the flow.
 */
export default function RemoteSensingTemplateComponent({
  onOpened,
}: {
  onOpened: () => void;
}) {
  const openFlow = useOpenWorkbenchFlow();
  const saveFlow = useSaveFlow();
  // Only a flow that is open in the editor is saved before leaving it.
  const { id: editedFlowId } = useParams();
  const assistantBusy = useAssistantManagerStore(
    (s) => s.isAssistantProcessing,
  );
  const flowLocked = useFlowStore(
    (s) => s.isBuilding || !!s.currentFlow?.locked,
  );
  return (
    <div
      className="flex flex-1 flex-col gap-4 overflow-auto"
      data-testid="remote-sensing-templates"
    >
      <div className="mx-3">
        <h3 className="text-lg font-semibold">遥感分析模板</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          选择分析任务和影像，生成由原生组件组成的工作流。同一任务和同一组影像只生成一次，再次选择会打开已有的那个工作流。
        </p>
      </div>
      <div className="mx-3 max-w-md rounded-lg border">
        <TemplatePanel
          disabled={!!editedFlowId && (flowLocked || assistantBusy)}
          save={editedFlowId ? saveFlow : async () => undefined}
          openFlow={async (id) => {
            await openFlow(id);
            onOpened();
          }}
          submitLabel={editedFlowId ? "保存当前图并打开模板" : "打开模板"}
          intro={
            editedFlowId
              ? "当前工作流先保存，模板在新工作流中打开。"
              : "模板在新工作流中打开。"
          }
        />
      </div>
    </div>
  );
}
