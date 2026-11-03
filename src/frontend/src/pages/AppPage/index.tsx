import { useEffect, useState } from "react";
import { useBlocker, useParams } from "react-router-dom";
import { FlowPageSlidingContainerContent } from "@/components/core/playgroundComponent/sliding-container/components/flow-page-sliding-container";
import { AssistantPanel } from "@/components/core/assistantPanel";
import { SidebarProvider } from "@/components/ui/sidebar";
import {
  SimpleSidebar,
  SimpleSidebarProvider,
} from "@/components/ui/simple-sidebar";
import { useGetFlow } from "@/controllers/API/queries/flows/use-get-flow";
import { useGetTypes } from "@/controllers/API/queries/flows/use-get-types";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import useApplyFlowToCanvas from "@/hooks/flows/use-apply-flow-to-canvas";
import useSaveFlow from "@/hooks/flows/use-save-flow";
import { SaveChangesModal } from "@/modals/saveChangesModal";
import useFlowStore from "@/stores/flowStore";
import useFlowsManagerStore from "@/stores/flowsManagerStore";
import { useTypesStore } from "@/stores/typesStore";
import { isSiblingFlowView } from "@/utils/flow-view-routing";
import { customStringify } from "@/utils/reactflowUtils";
import { AppWidgetRegion } from "./components/app-widget-region";

const CHAT_PANEL_WIDTH = "420px";
/** Fractions of the page width the chat panel may be dragged between. */
const CHAT_PANEL_MIN_WIDTH = 0.2;
const CHAT_PANEL_MAX_WIDTH = 0.7;

/**
 * Runtime view of a flow: visual widgets on the left, the playground chat
 * docked on the right.
 *
 * A sibling mode of ``FlowPage`` rather than a separate surface — both are
 * authenticated, both operate on the same flow, and the user moves between
 * them freely. The flow therefore has to be loaded into ``flowStore`` exactly
 * as the editor loads it: the chat and the build machinery read their
 * inputs/outputs from the store, not from the canvas.
 */
export default function AppPage(): JSX.Element {
  const { id } = useParams();
  const navigate = useCustomNavigate();

  const types = useTypesStore((state) => state.types);
  useGetTypes({ enabled: Object.keys(types).length <= 0 });

  const currentFlow = useFlowStore((state) => state.currentFlow);
  const hasChatInput = useFlowStore((state) =>
    state.nodes.some((node) => node.data.type === "ChatInput"),
  );
  const setOnFlowPage = useFlowStore((state) => state.setOnFlowPage);

  const flows = useFlowsManagerStore((state) => state.flows);
  const currentFlowId = useFlowsManagerStore((state) => state.currentFlowId);
  const setCurrentFlow = useFlowsManagerStore((state) => state.setCurrentFlow);
  const currentSavedFlow = useFlowsManagerStore((state) => state.currentFlow);
  const saveFlow = useSaveFlow();
  const changesNotSaved =
    !!currentFlow &&
    customStringify(currentFlow) !== customStringify(currentSavedFlow);
  const isBuilding = useFlowStore((state) => state.isBuilding);
  // Canvas edits remain live in this sibling view. Protect them when the
  // user leaves the flow from the result screen too, including an empty graph.
  const blocker = useBlocker(
    ({ nextLocation }) =>
      changesNotSaved && !isSiblingFlowView(nextLocation.pathname, id),
  );
  useEffect(() => {
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (changesNotSaved || isBuilding) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [changesNotSaved, isBuilding]);

  const { mutateAsync: getFlow } = useGetFlow();
  const applyFlowToCanvas = useApplyFlowToCanvas();

  const [isChatOpen, setIsChatOpen] = useState(true);
  const [isChatFullscreen, setIsChatFullscreen] = useState(false);

  // ``onFlowPage`` gates the header's flow breadcrumb and build logging, both
  // of which the App page wants.
  useEffect(() => {
    setOnFlowPage(true);

    return () => {
      setOnFlowPage(false);
      // Mirrors FlowPage: switching back to the canvas keeps the same
      // in-memory flow, so neither view has to save or refetch on toggle.
      if (!isSiblingFlowView(window.location.pathname, id)) {
        setCurrentFlow(undefined);
      }
    };
  }, [id]);

  // Mirrors FlowPage's load guard: fetch only when the store is empty, so
  // moving Editor -> App preserves unsaved graph edits instead of silently
  // replacing them with the server copy.
  useEffect(() => {
    const loadFlowIntoStore = async () => {
      if (!flows || currentFlowId !== "" || Object.keys(types).length === 0) {
        return;
      }

      const existingFlow = flows.find((flow) => flow.id === id);
      if (!existingFlow) {
        navigate("/all");
        return;
      }

      applyFlowToCanvas(await getFlow({ id: existingFlow.id }));
    };

    loadFlowIntoStore();
  }, [id, flows, currentFlowId, types]);

  return (
    <>
      <div className="flow-page-positioning">
        {currentFlow && (
          <div className="flex h-full overflow-hidden" data-testid="app-page">
            <SimpleSidebarProvider
              width={CHAT_PANEL_WIDTH}
              minWidth={CHAT_PANEL_MIN_WIDTH}
              maxWidth={CHAT_PANEL_MAX_WIDTH}
              open={isChatOpen}
              onOpenChange={setIsChatOpen}
              fullscreen={isChatFullscreen}
              onMaxWidth={() => {
                setIsChatFullscreen(true);
                setIsChatOpen(true);
              }}
            >
              <main className="flex min-w-0 flex-1 overflow-hidden">
                <AppWidgetRegion
                  isChatOpen={isChatOpen}
                  onShowChat={() => setIsChatOpen(true)}
                />
              </main>
              <SimpleSidebar resizable={!isChatFullscreen} className="h-full">
                {hasChatInput ? (
                  <FlowPageSlidingContainerContent
                    isFullscreen={isChatFullscreen}
                    setIsFullscreen={setIsChatFullscreen}
                  />
                ) : (
                  <SidebarProvider
                    defaultOpen={false}
                    className="h-full min-h-0"
                  >
                    <div
                      className="flex h-full min-h-0 w-full flex-col"
                      data-testid="app-flow-assistant"
                    >
                      <p className="shrink-0 border-b px-4 py-2 text-xs text-muted-foreground">
                        本流程的工作流助手 · 可追问运行结果或调整流程
                      </p>
                      <div className="min-h-0 flex-1">
                        <AssistantPanel
                          docked
                          isOpen={isChatOpen}
                          onClose={() => setIsChatOpen(false)}
                        />
                      </div>
                    </div>
                  </SidebarProvider>
                )}
              </SimpleSidebar>
            </SimpleSidebarProvider>
          </div>
        )}
      </div>
      {blocker.state === "blocked" && currentFlow && (
        <SaveChangesModal
          onSave={() => {
            void saveFlow().then(
              () => blocker.proceed?.(),
              () => blocker.reset?.(),
            );
          }}
          onCancel={() => blocker.reset?.()}
          onProceed={() => blocker.proceed?.()}
          flowName={currentFlow.name}
          lastSaved={
            currentSavedFlow?.updated_at
              ? new Date(currentSavedFlow.updated_at).toLocaleString()
              : undefined
          }
          autoSave={false}
        />
      )}
    </>
  );
}
