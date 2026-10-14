import { Outlet, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";

/** Secondary management/history routes; the editor itself is FlowPage. */
export default function WorkspaceShell() {
  const navigate = useNavigate();
  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b px-4 text-sm">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate("/workspace")}
        >
          ← 返回画布
        </Button>
        <span className="mr-auto font-medium">Terraflow</span>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate("/workspace/runs")}
        >
          历史分析记录
        </Button>
        <Button variant="ghost" size="sm" onClick={() => navigate("/flows")}>
          全部工作流
        </Button>
      </header>
      <main className="min-h-0 flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
