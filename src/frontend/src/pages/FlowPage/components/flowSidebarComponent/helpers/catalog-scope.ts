import type { APIDataType } from "@/types/api";
import { SIDEBAR_BUNDLES } from "@/utils/styleUtils";

export type CatalogScope = "all" | "geo" | "basic";

export function isCatalogCategory(category: string): boolean {
  return (
    category !== "MCP" &&
    category !== "custom_component" &&
    !SIDEBAR_BUNDLES.some((bundle) => bundle.name === category)
  );
}

/** View filtering only; never changes the registry available to the assistant. */
export function filterCatalogScope(
  data: APIDataType,
  scope: CatalogScope,
): APIDataType {
  if (scope === "all") return data;
  return Object.fromEntries(
    Object.entries(data)
      .filter(([category]) => isCatalogCategory(category))
      .map(([category, components]) => [
        category,
        Object.fromEntries(
          Object.entries(components).filter(([type]) => {
            const geospatial =
              type.startsWith("Terrabox") ||
              ["geo_workflow", "disaster_response", "earth_sci"].includes(
                category,
              );
            return scope === "geo" ? geospatial : !geospatial;
          }),
        ),
      ]),
  );
}
