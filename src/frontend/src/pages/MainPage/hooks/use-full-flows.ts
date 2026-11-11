import { type UseQueryResult, useQueries } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import type { FlowType } from "@/types/flow";
import { processFlows } from "@/utils/reactflowUtils";

// Module-level so React Query keeps the combined result stable between renders.
function combine(results: UseQueryResult<FlowType>[]) {
  return {
    loading: results.some((result) => result.isPending),
    rows: results.map((result) => result.data),
  };
}

/**
 * Full rows (graph data, edit time) for flows known only by their header, so a list built
 * from the flows store offers the same row actions as a page of the folder listing.
 * A flow whose request fails stays in the list with its header fields.
 */
export function useFullFlows(headers: FlowType[], enabled: boolean) {
  const { loading, rows } = useQueries({
    queries: headers.map((flow) => ({
      queryKey: ["useFullFlows", flow.id],
      queryFn: async () => {
        const response = await api.get<FlowType>(
          `${getURL("FLOWS")}/${flow.id}`,
        );
        return processFlows([response.data]).flows[0];
      },
      enabled,
      retry: 1,
      refetchOnWindowFocus: false,
    })),
    combine,
  });
  const flows = useMemo(
    () =>
      headers
        .map((flow, index) => rows[index] ?? flow)
        .sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? "")),
    [headers, rows],
  );
  return { loading: enabled && loading, flows };
}
