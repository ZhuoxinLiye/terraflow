import { useCallback } from "react";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import useFlowsManagerStore from "@/stores/flowsManagerStore";
import type { FlowType } from "@/types/flow";

/**
 * Opens a flow the workbench service created. The editor opens only flows the flows store
 * lists and sends any other id back to the list; a flow created outside the browser is not
 * in the store until its next refresh, so it is added here first.
 */
export function useOpenWorkbenchFlow() {
  const navigate = useCustomNavigate();
  return useCallback(
    async (id: string) => {
      const known = () =>
        useFlowsManagerStore.getState().flows?.some((flow) => flow.id === id);
      if (!known()) {
        try {
          const { data } = await api.get<FlowType>(`${getURL("FLOWS")}/${id}`);
          const { flows, setFlows } = useFlowsManagerStore.getState();
          if (!known()) setFlows([...(flows ?? []), data]);
        } catch {
          // The editor decides: it shows the flow once the store has it, else the list.
        }
      }
      navigate(`/flow/${id}`);
    },
    [navigate],
  );
}
