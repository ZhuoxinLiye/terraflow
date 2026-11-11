import { render, screen } from "@testing-library/react";
import type { WorkbenchFlowSource } from "@/pages/WorkspacePage/flow-source";
import type { FlowType } from "@/types/flow";
import ListComponent from "../index";

// Synthetic flow rows; only the source line added for workbench flows is under test.
jest.mock("react-router-dom", () => ({ useParams: () => ({}) }));
jest.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { time?: string }) =>
      key === "mainPage.editedAgo" ? `Edited ${options?.time} ago` : key,
  }),
}));
jest.mock("@/components/common/genericIconComponent", () => ({
  __esModule: true,
  default: () => <span />,
}));
jest.mock("@/components/core/cardComponent/hooks/use-on-drag-start", () => ({
  __esModule: true,
  default: () => ({ onDragStart: jest.fn() }),
}));
jest.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  DropdownMenuTrigger: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  DropdownMenuContent: () => null,
}));
jest.mock("@/customization/hooks/use-custom-navigate", () => ({
  useCustomNavigate: () => jest.fn(),
}));
jest.mock("@/hooks/flows/use-delete-flow", () => ({
  __esModule: true,
  default: () => ({ deleteFlow: jest.fn() }),
}));
jest.mock("@/modals/deleteConfirmationModal", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/modals/exportModal", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/modals/flowSettingsModal", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/stores/alertStore", () => ({
  __esModule: true,
  default: () => jest.fn(),
}));
jest.mock("@/utils/reactflowUtils", () => ({ downloadFlow: jest.fn() }));
jest.mock("@/utils/styleUtils", () => ({ swatchColors: ["bg-a", "bg-b"] }));
jest.mock("@/utils/utils", () => ({
  cn: (...parts: unknown[]) => parts.filter(Boolean).join(" "),
  getNumberFromString: () => 0,
}));
jest.mock("../../../hooks/use-description-modal", () => ({
  __esModule: true,
  default: () => "flow",
}));
jest.mock("../../../utils/get-template-style", () => ({
  useGetTemplateStyle: () => ({ getIcon: async () => "Workflow" }),
}));
jest.mock("../../dropdown", () => ({ __esModule: true, default: () => null }));

const flow = {
  id: "flow-1",
  name: "单景水体提取 · synthetic",
  description: "",
  data: null,
  updated_at: new Date().toISOString(),
} as FlowType;

const source: WorkbenchFlowSource = {
  kind: "template",
  key: "template:water_extent:synthetic.scene",
  origin: "模板 · 单景水体提取",
  scenarioTitle: "单景水体提取",
  imagery: [{ role: "scene", label: "影像", scene: "synthetic.scene" }],
  plan: ["inspect_geotiff", "water_extent"],
};

function renderRow(props: Partial<Parameters<typeof ListComponent>[0]>) {
  return render(
    <ListComponent
      flowData={flow}
      selected={false}
      setSelected={jest.fn()}
      shiftPressed={false}
      {...props}
    />,
  );
}

describe("ListComponent workbench source line", () => {
  it("shows origin, imagery and plan for a workbench flow", async () => {
    renderRow({ source });
    const line = await screen.findByTestId("flow-source-flow-1");
    expect(line).toHaveTextContent("工作台");
    expect(line).toHaveTextContent(
      "模板 · 单景水体提取 · 影像 synthetic.scene · 步骤 inspect_geotiff → water_extent",
    );
    // The full text stays readable when the row truncates it.
    expect(line).toHaveAttribute(
      "title",
      "模板 · 单景水体提取 · 影像 synthetic.scene · 步骤 inspect_geotiff → water_extent",
    );
  });

  it("adds nothing to a flow that did not come from the workbench", async () => {
    renderRow({ source: null });
    await screen.findByTestId("flow-name-flow-1");
    expect(screen.queryByTestId("flow-source-flow-1")).toBeNull();
    expect(screen.getByTestId("list-card")).toHaveTextContent(/Edited .* ago/);
  });

  it("omits the edit time for a row that has none", async () => {
    renderRow({ flowData: { ...flow, updated_at: undefined }, source });
    await screen.findByTestId("flow-source-flow-1");
    expect(screen.getByTestId("list-card")).not.toHaveTextContent("Edited");
  });
});
