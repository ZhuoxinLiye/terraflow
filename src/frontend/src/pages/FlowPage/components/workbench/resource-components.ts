import type { APIClassType } from "@/types/api";

export function sceneComponent(
  component: APIClassType | undefined,
  sceneId: string,
): APIClassType | null {
  if (!component?.template?.scene_id) return null;
  const copy = structuredClone(component);
  copy.template.scene_id.value = sceneId;
  copy.template.scene_id.options = Array.from(
    new Set([...(copy.template.scene_id.options ?? []), sceneId]),
  );
  return copy;
}

export function componentDragData(component: APIClassType, type: string) {
  return JSON.stringify({ type, node: component });
}
