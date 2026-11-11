import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import TemplatePanel from "../TemplatePanel";

// Synthetic scenario and scenes; the workbench service is mocked.
const createSceneTemplate = jest.fn();

jest.mock("@/pages/WorkspacePage/create-scene-template", () => ({
  createSceneTemplate: (...args: unknown[]) => createSceneTemplate(...args),
}));

jest.mock("@/pages/WorkspacePage/api", () => ({
  API: "/api/workspace",
  apiJson: jest.fn(async () => ({
    scenarios: [
      {
        id: "water_change",
        title: "水体变化",
        summary: "synthetic summary",
        canvas_template: true,
        input_kinds: ["sar_backscatter"],
        inputs: [
          { role: "before", label: "前期影像" },
          { role: "after", label: "后期影像" },
        ],
      },
      { id: "optical_water", title: "光学水体提取", inputs: [] },
    ],
  })),
  pickableScenes: (scenes: unknown[]) => scenes,
  useScenes: () => ({
    scenes: [
      {
        id: "synthetic.before",
        title: "before",
        collection_title: "synthetic",
        input_kind: "sar_backscatter",
      },
      {
        id: "synthetic.after",
        title: "after",
        collection_title: "synthetic",
        input_kind: "sar_backscatter",
      },
      {
        id: "synthetic.optical",
        title: "optical",
        collection_title: "synthetic",
        input_kind: "optical",
      },
    ],
  }),
}));

jest.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    onClick,
    disabled,
  }: {
    children: React.ReactNode;
    onClick?: () => void;
    disabled?: boolean;
  }) => (
    <button type="button" onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
}));

async function fillForm() {
  await screen.findByRole("option", { name: "水体变化" });
  fireEvent.change(screen.getByLabelText("分析任务"), {
    target: { value: "water_change" },
  });
  fireEvent.change(screen.getByLabelText("前期影像"), {
    target: { value: "synthetic.before" },
  });
  fireEvent.change(screen.getByLabelText("后期影像"), {
    target: { value: "synthetic.after" },
  });
}

describe("TemplatePanel", () => {
  beforeEach(() => createSceneTemplate.mockReset());

  it("lists only scenarios that have a canvas template and matching imagery", async () => {
    render(
      <TemplatePanel disabled={false} save={jest.fn()} openFlow={jest.fn()} />,
    );
    await screen.findByRole("option", { name: "水体变化" });
    expect(screen.queryByRole("option", { name: "光学水体提取" })).toBeNull();
    fireEvent.change(screen.getByLabelText("分析任务"), {
      target: { value: "water_change" },
    });
    expect(
      screen.getAllByRole("option", { name: /synthetic · before/ }),
    ).toHaveLength(2);
    expect(screen.queryByRole("option", { name: /optical/ })).toBeNull();
  });

  it("saves the current flow, creates once and opens the returned flow", async () => {
    const order: string[] = [];
    const save = jest.fn(async () => {
      order.push("save");
    });
    const openFlow = jest.fn(async () => {
      order.push("open");
    });
    createSceneTemplate.mockImplementation(async () => {
      order.push("create");
      return { status: "created", flowId: "new-flow" };
    });
    render(<TemplatePanel disabled={false} save={save} openFlow={openFlow} />);
    await fillForm();
    fireEvent.click(
      screen.getByRole("button", { name: "保存当前图并打开模板" }),
    );
    await waitFor(() => expect(openFlow).toHaveBeenCalledWith("new-flow"));
    expect(order).toEqual(["save", "create", "open"]);
    expect(createSceneTemplate).toHaveBeenCalledTimes(1);
    expect(createSceneTemplate).toHaveBeenCalledWith(
      "water_change",
      { before: "synthetic.before", after: "synthetic.after" },
      { replaceStale: false },
    );
  });

  it("does not create while the same scene fills two roles", async () => {
    render(
      <TemplatePanel disabled={false} save={jest.fn()} openFlow={jest.fn()} />,
    );
    await fillForm();
    fireEvent.change(screen.getByLabelText("后期影像"), {
      target: { value: "synthetic.before" },
    });
    expect(
      screen.getByRole("button", { name: "保存当前图并打开模板" }),
    ).toBeDisabled();
  });

  it("asks before dropping an index entry whose flow was deleted", async () => {
    const openFlow = jest.fn();
    createSceneTemplate.mockResolvedValueOnce({
      status: "stale",
      flowId: "gone-flow",
    });
    render(
      <TemplatePanel disabled={false} save={jest.fn()} openFlow={openFlow} />,
    );
    await fillForm();
    fireEvent.click(
      screen.getByRole("button", { name: "保存当前图并打开模板" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "索引中登记的这个模板工作流已被删除",
    );
    expect(openFlow).not.toHaveBeenCalled();

    createSceneTemplate.mockResolvedValueOnce({
      status: "created",
      flowId: "new-flow",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "清除这条旧记录并重新生成" }),
    );
    await waitFor(() => expect(openFlow).toHaveBeenCalledWith("new-flow"));
    expect(createSceneTemplate).toHaveBeenLastCalledWith(
      "water_change",
      expect.any(Object),
      { replaceStale: true },
    );
  });

  it("shows other failures without offering to change the index", async () => {
    createSceneTemplate.mockRejectedValueOnce(new Error("两景影像不能相同。"));
    render(
      <TemplatePanel disabled={false} save={jest.fn()} openFlow={jest.fn()} />,
    );
    await fillForm();
    fireEvent.click(
      screen.getByRole("button", { name: "保存当前图并打开模板" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "两景影像不能相同。",
    );
    expect(
      screen.queryByRole("button", { name: "清除这条旧记录并重新生成" }),
    ).toBeNull();
  });
});
