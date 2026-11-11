import { renderHook } from "@testing-library/react";
import { useOpenWorkbenchFlow } from "../use-open-workbench-flow";

// Synthetic ids; the backend and the router are mocked.
const navigate = jest.fn();
const get = jest.fn();
const store: { flows: Array<{ id: string }> | undefined; setFlows: jest.Mock } =
  {
    flows: [],
    setFlows: jest.fn((flows: Array<{ id: string }>) => {
      store.flows = flows;
    }),
  };

jest.mock("@/controllers/API/api", () => ({
  api: { get: (...args: unknown[]) => get(...args) },
}));
jest.mock("@/controllers/API/helpers/constants", () => ({
  getURL: () => "/api/v1/flows",
}));
jest.mock("@/customization/hooks/use-custom-navigate", () => ({
  useCustomNavigate: () => navigate,
}));
jest.mock("@/stores/flowsManagerStore", () => ({
  __esModule: true,
  default: { getState: () => store },
}));

describe("useOpenWorkbenchFlow", () => {
  beforeEach(() => {
    navigate.mockReset();
    get.mockReset();
    store.setFlows.mockClear();
    store.flows = [{ id: "known-flow" }];
  });

  it("adds a flow created outside the browser to the store before opening it", async () => {
    const order: string[] = [];
    get.mockImplementation(async () => {
      order.push("get");
      return { data: { id: "new-flow", name: "synthetic" } };
    });
    store.setFlows.mockImplementationOnce((flows) => {
      order.push("store");
      store.flows = flows;
    });
    navigate.mockImplementation(() => order.push("navigate"));
    const { result } = renderHook(() => useOpenWorkbenchFlow());
    await result.current("new-flow");
    expect(get).toHaveBeenCalledWith("/api/v1/flows/new-flow");
    expect(store.flows?.map((flow) => flow.id)).toEqual([
      "known-flow",
      "new-flow",
    ]);
    expect(order).toEqual(["get", "store", "navigate"]);
    expect(navigate).toHaveBeenCalledWith("/flow/new-flow");
  });

  it("opens a flow the store already lists without another request", async () => {
    const { result } = renderHook(() => useOpenWorkbenchFlow());
    await result.current("known-flow");
    expect(get).not.toHaveBeenCalled();
    expect(store.setFlows).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith("/flow/known-flow");
  });

  it("still navigates when the flow cannot be read", async () => {
    get.mockRejectedValue(new Error("network"));
    const { result } = renderHook(() => useOpenWorkbenchFlow());
    await result.current("new-flow");
    expect(store.setFlows).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith("/flow/new-flow");
  });
});
