import { Panel } from "@xyflow/react";
import { AnimatePresence, motion } from "framer-motion";
import { memo, useEffect, useState } from "react";
import { Separator } from "@/components/ui/separator";
import type { AllNodeType } from "@/types/flow";
import { cn } from "@/utils/utils";
import InspectionPanelFields from "./components/InspectionPanelFields";
import InspectionPanelHeader from "./components/InspectionPanelHeader";

interface InspectionPanelProps {
  selectedNode: AllNodeType | null;
  docked?: boolean;
}

const InspectionPanel = memo(function InspectionPanel({
  selectedNode,
  docked = false,
}: InspectionPanelProps) {
  const [isEditingFields, setIsEditingFields] = useState(false);

  // Reset edit mode when panel closes or node changes
  useEffect(() => {
    setIsEditingFields(false);
  }, [selectedNode?.id]);

  if (docked)
    return selectedNode?.type === "genericNode" ? (
      <div className="relative flex min-h-0 flex-1 flex-col overflow-y-auto overflow-x-hidden">
        <InspectionPanelHeader
          data={selectedNode.data}
          isEditingFields={isEditingFields}
          setIsEditingFields={setIsEditingFields}
        />
        <Separator />
        <InspectionPanelFields
          data={selectedNode.data}
          key={selectedNode.id}
          isEditingFields={isEditingFields}
        />
      </div>
    ) : null;

  return (
    <AnimatePresence mode="wait">
      {selectedNode && selectedNode.type === "genericNode" && (
        <Panel
          position="top-right"
          className={cn(
            "!top-[3rem] !-right-2 !bottom-10 relative",
            "w-[340px]",
            "pointer-events-none",
          )}
        >
          <motion.div
            initial={{ x: "100%", opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: "100%", opacity: 0 }}
            transition={{ duration: 0, ease: "easeInOut" }}
            className={cn(
              "max-h-full w-[320px] ml-auto",
              "rounded-xl border bg-background shadow-lg",
              "overflow-y-auto overflow-x-visible flex flex-col pointer-events-auto",
            )}
          >
            <InspectionPanelHeader
              data={selectedNode.data}
              isEditingFields={isEditingFields}
              setIsEditingFields={setIsEditingFields}
            />
            <Separator className="my-0.5" />
            <InspectionPanelFields
              data={selectedNode.data}
              key={selectedNode.id}
              isEditingFields={isEditingFields}
            />
          </motion.div>
        </Panel>
      )}
    </AnimatePresence>
  );
});

export default InspectionPanel;
