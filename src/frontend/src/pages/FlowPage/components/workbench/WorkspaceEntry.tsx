import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useGetRefreshFlowsQuery } from "@/controllers/API/queries/flows/use-get-refresh-flows-query";
import useAddFlow from "@/hooks/flows/use-add-flow";
import useFlowsManagerStore from "@/stores/flowsManagerStore";

/** The existing workspace URL now opens the native editor, never an iframe. */
export default function WorkspaceEntry() {
  const query = useGetRefreshFlowsQuery({
    get_all: true,
    header_flows: true,
    remove_example_flows: true,
  });
  const flows = useFlowsManagerStore((s) => s.flows);
  const create = useAddFlow();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const last = localStorage.getItem("terraflow-workbench-flow");
  const target =
    flows?.find((flow) => flow.id === last) ??
    flows?.filter((flow) => !flow.is_component)[0];
  const section = pathname.includes("/data")
    ? "data"
    : pathname.includes("/tools")
      ? "components"
      : pathname.includes("/scenarios")
        ? "templates"
        : "";
  if (target)
    return (
      <Navigate
        replace
        to={`/flow/${target.id}${section ? `?resource=${section}` : ""}`}
      />
    );
  return (
    <div className="flex h-screen items-center justify-center bg-background">
      <div className="space-y-3 text-center">
        <h1 className="text-lg font-semibold">Terraflow 工作台</h1>
        <p className="text-sm text-muted-foreground">
          在原生画布中选择数据、搭建工作流并查看结果。
        </p>
        <Button
          disabled={!flows || busy}
          onClick={async () => {
            setBusy(true);
            try {
              const id = await create({ new_blank: true });
              navigate(`/flow/${id}`);
            } catch {
              setError("创建失败，请重试。");
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "创建中…" : flows ? "新建工作流" : "载入工作流…"}
        </Button>
        {error && <p role="alert">{error}</p>}
        {query.isError && (
          <Button variant="outline" onClick={() => void query.refetch()}>
            重新载入工作流
          </Button>
        )}
      </div>
    </div>
  );
}
