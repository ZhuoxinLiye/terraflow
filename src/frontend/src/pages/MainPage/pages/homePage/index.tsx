import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useParams, useSearchParams } from "react-router-dom";
import PaginatorComponent from "@/components/common/paginatorComponent";
import ProjectFilesTab from "@/components/common/projectFilesTab";
import CardsWrapComponent from "@/components/core/cardsWrapComponent";
import { useStartNewFlow } from "@/components/core/flowBuilderWelcome/hooks/use-start-new-flow";
import { IS_MAC } from "@/constants/constants";
import { useGetFolderQuery } from "@/controllers/API/queries/folders/use-get-folder";
import { CustomBanner } from "@/customization/components/custom-banner";
import { CustomMcpServerTab } from "@/customization/components/custom-McpServerTab";
import {
  ENABLE_DATASTAX_TERRAFLOW,
  ENABLE_MCP,
} from "@/customization/feature-flags";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import { useWorkbenchFlowSources } from "@/pages/WorkspacePage/flow-source";
import useFlowsManagerStore from "@/stores/flowsManagerStore";
import { useFolderStore } from "@/stores/foldersStore";
import HeaderComponent from "../../components/header";
import ListComponent from "../../components/list";
import ListSkeleton from "../../components/listSkeleton";
import ModalsComponent from "../../components/modalsComponent";
import { useFullFlows } from "../../hooks/use-full-flows";
import useFileDrop from "../../hooks/use-on-file-drop";
import type { FlowTabType } from "../../types";
import DeploymentsPage from "../deploymentsPage/deployments-page";
import EmptyFolder from "../emptyFolder";
import { isFolderEmpty } from "./utils/isFolderEmpty";

const HomePage = ({ type }: { type: "flows" | "components" | "mcp" }) => {
  const { t } = useTranslation();
  const [view, setView] = useState<"grid" | "list">(() => {
    const savedView = localStorage.getItem("view");
    return savedView === "grid" || savedView === "list" ? savedView : "list";
  });
  const [newProjectModal, setNewProjectModal] = useState(false);
  const { folderId } = useParams();
  const location = useLocation();
  const [pageIndex, setPageIndex] = useState(1);
  const [pageSize, setPageSize] = useState(12);
  const [search, setSearch] = useState("");
  const [isEmptyFolder, setIsEmptyFolder] = useState<boolean | null>(null);
  const navigate = useCustomNavigate();

  const [flowType, setFlowType] = useState<FlowTabType>(
    (location.state as Record<string, unknown>)?.flowType === "deployments"
      ? "deployments"
      : type,
  );
  const myCollectionId = useFolderStore((state) => state.myCollectionId);
  const folders = useFolderStore((state) => state.folders);
  const folderName =
    folders.find((folder) => folder.id === folderId)?.name ??
    folders[0]?.name ??
    "";
  const flows = useFlowsManagerStore((state) => state.flows);
  // The primary "New Flow" handler — creates an empty flow, primes the
  // welcome overlay store, and navigates to the canvas. Replaces the old
  // "open the templates modal" behavior. The templates modal is still
  // reachable from inside the welcome via "Browse more templates".
  const startNewFlow = useStartNewFlow();

  useEffect(() => {
    // Only check if we have a folderId and folders have loaded
    if (folderId && folders && folders.length > 0) {
      const folderExists = folders.find((folder) => folder.id === folderId);
      if (!folderExists) {
        // Folder doesn't exist for this user, redirect to /all
        console.error("Invalid folderId, redirecting to /all");
        navigate("/all");
      }
    }
  }, [folderId, folders, navigate]);

  const { data: folderData, isLoading } = useGetFolderQuery({
    id: folderId ?? myCollectionId!,
    page: pageIndex,
    size: pageSize,
    is_component: flowType === "components",
    is_flow: flowType === "flows",
    search,
  });

  const data = {
    flows: folderData?.flows?.items ?? [],
    name: folderData?.folder?.name ?? "",
    description: folderData?.folder?.description ?? "",
    parent_id: folderData?.folder?.parent_id ?? "",
    components: folderData?.folder?.components ?? [],
    pagination: {
      page: folderData?.flows?.page ?? 1,
      size: folderData?.flows?.size ?? 12,
      total: folderData?.flows?.total ?? 0,
      pages: folderData?.flows?.pages ?? 0,
    },
  };

  // Flows the workbench generated keep their recorded source in this list. The old
  // workbench list page showed only that subset; `?source=workbench` shows the same one.
  const workbench = useWorkbenchFlowSources(type === "flows");
  const [searchParams, setSearchParams] = useSearchParams();
  const workbenchOnly =
    flowType === "flows" && searchParams.get("source") === "workbench";
  const setWorkbenchOnly = useCallback(
    (only: boolean) => {
      const next = new URLSearchParams(searchParams);
      if (only) next.set("source", "workbench");
      else next.delete("source");
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );
  const workbenchFlows = useMemo(
    () =>
      (flows ?? []).filter(
        (flow) =>
          !flow.is_component &&
          flow.folder_id === (folderId ?? myCollectionId) &&
          workbench.sourceOf(flow) !== null,
      ),
    [flows, folderId, myCollectionId, workbench.sourceOf],
  );
  // The store knows flows by header only; the subset view loads their full rows.
  const workbenchRows = useFullFlows(workbenchFlows, workbenchOnly);
  const listedFlows = useMemo(
    () =>
      workbenchOnly
        ? workbenchRows.flows.filter((flow) =>
            flow.name.toLowerCase().includes(search.trim().toLowerCase()),
          )
        : data.flows,
    [workbenchOnly, workbenchRows.flows, search, folderData?.flows?.items],
  );

  useEffect(() => {
    localStorage.setItem("view", view);
  }, [view]);

  const handlePageChange = useCallback((newPageIndex, newPageSize) => {
    setPageIndex(newPageIndex);
    setPageSize(newPageSize);
  }, []);

  const onSearch = useCallback((newSearch) => {
    setSearch(newSearch);
    setPageIndex(1);
  }, []);

  useEffect(() => {
    // Wait until both the global flows store has populated and the folder
    // query has settled (success or error) before deciding whether the
    // folder is empty. This avoids a one-frame flash of <EmptyFolder> on
    // initial mount and right after login, when the store is briefly
    // stale. Gating on isLoading instead of folderData lets us still
    // resolve when the query errors out (e.g. when there is no valid
    // folder id to query, after deleting all folders).
    if (flows === undefined || isLoading) return;
    setIsEmptyFolder(
      isFolderEmpty({
        flows,
        folderId: folderId ?? myCollectionId ?? "",
        folderTotal: folderData?.flows?.total,
        enableMcp: ENABLE_MCP,
      }),
    );
  }, [flows, folderId, myCollectionId, folderData, isLoading]);

  const handleFileDrop = useFileDrop(isEmptyFolder ? undefined : flowType);

  useEffect(() => {
    if (
      !isEmptyFolder &&
      flows?.find(
        (flow) =>
          flow.folder_id === (folderId ?? myCollectionId) &&
          flow.is_component === (flowType === "components"),
      ) === undefined
    ) {
      const otherTabHasItems =
        flows?.find(
          (flow) =>
            flow.folder_id === (folderId ?? myCollectionId) &&
            flow.is_component === (flowType === "flows"),
        ) !== undefined;

      if (otherTabHasItems) {
        setFlowType(flowType === "flows" ? "components" : "flows");
      }
    }
  }, [isEmptyFolder]);

  const [selectedFlows, setSelectedFlows] = useState<string[]>([]);
  const [lastSelectedIndex, setLastSelectedIndex] = useState<number | null>(
    null,
  );
  const [isShiftPressed, setIsShiftPressed] = useState(false);
  const [isCtrlPressed, setIsCtrlPressed] = useState(false);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Only track these keys when we're in list/selection mode and not when a modal is open
      // or when an input field is focused
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        (e.target instanceof HTMLElement && e.target.isContentEditable)
      ) {
        return;
      }

      if (e.key === "Shift") {
        setIsShiftPressed(true);
      } else if ((!IS_MAC && e.key === "Control") || e.key === "Meta") {
        setIsCtrlPressed(true);
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        (e.target instanceof HTMLElement && e.target.isContentEditable)
      ) {
        return;
      }

      if (e.key === "Shift") {
        setIsShiftPressed(false);
      } else if ((!IS_MAC && e.key === "Control") || e.key === "Meta") {
        setIsCtrlPressed(false);
      }
    };

    // Reset key states when window loses focus
    const handleBlur = () => {
      setIsShiftPressed(false);
      setIsCtrlPressed(false);
    };

    // Only add listeners if we're in flows or components mode, not MCP mode
    if (flowType === "flows" || flowType === "components") {
      document.addEventListener("keydown", handleKeyDown);
      document.addEventListener("keyup", handleKeyUp);
      window.addEventListener("blur", handleBlur);
    }

    // Clean up event listeners when component unmounts
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("keyup", handleKeyUp);
      window.removeEventListener("blur", handleBlur);

      // Reset key states on unmount
      setIsShiftPressed(false);
      setIsCtrlPressed(false);
    };
  }, [flowType]);

  const setSelectedFlow = useCallback(
    (selected: boolean, flowId: string, index: number) => {
      setLastSelectedIndex(index);
      if (isShiftPressed && lastSelectedIndex !== null) {
        // Find the indices of the last selected and current flow
        const flows = listedFlows;

        // Determine the range to select
        const start = Math.min(lastSelectedIndex, index);
        const end = Math.max(lastSelectedIndex, index);
        // Get all flow IDs in the range
        const flowsToSelect = flows
          .slice(start, end + 1)
          .map((flow) => flow.id);

        // Update selection
        if (selected) {
          setSelectedFlows((prev) =>
            Array.from(new Set([...prev, ...flowsToSelect])),
          );
        } else {
          setSelectedFlows((prev) =>
            prev.filter((id) => !flowsToSelect.includes(id)),
          );
        }
      } else {
        if (selected) {
          setSelectedFlows([...selectedFlows, flowId]);
        } else {
          setSelectedFlows(selectedFlows.filter((id) => id !== flowId));
        }
      }
    },
    [selectedFlows, lastSelectedIndex, listedFlows, isShiftPressed],
  );

  useEffect(() => {
    setSelectedFlows((old) => {
      const kept = old.filter((id) =>
        listedFlows.some((flow) => flow.id === id),
      );
      return kept.length === old.length ? old : kept;
    });
  }, [listedFlows]);

  // Reset key states when navigating away
  useEffect(() => {
    return () => {
      setIsShiftPressed(false);
      setIsCtrlPressed(false);
    };
  }, [folderId]);

  return (
    <CardsWrapComponent
      onFileDrop={
        flowType === "mcp" || flowType === "files" ? undefined : handleFileDrop
      }
      dragMessage={
        isEmptyFolder
          ? t("home.dragFlowsOrComponents")
          : t("home.dragFlowType", { flowType })
      }
    >
      <div
        className="flex h-full w-full flex-col overflow-y-auto"
        data-testid="cards-wrapper"
      >
        <div className="flex h-full w-full flex-col 3xl:container">
          {ENABLE_DATASTAX_TERRAFLOW && <CustomBanner />}
          <div className="flex flex-1 flex-col justify-start p-4">
            <div className="flex h-full flex-col justify-start">
              <HeaderComponent
                folderName={folderName}
                flowType={flowType}
                setFlowType={setFlowType}
                view={view}
                setView={setView}
                setNewProjectModal={setNewProjectModal}
                onNewFlow={startNewFlow}
                setSearch={onSearch}
                isEmptyFolder={isEmptyFolder === true}
                selectedFlows={selectedFlows}
              />
              {flowType === "flows" &&
                isEmptyFolder === false &&
                (workbenchOnly || workbenchFlows.length > 0) && (
                  <div
                    className="mt-3 flex flex-wrap items-center gap-2 text-xs"
                    data-testid="flow-source-filter"
                  >
                    <span className="text-muted-foreground">来源</span>
                    {[
                      { only: false, label: "全部" },
                      {
                        only: true,
                        label: `工作台生成（${workbenchFlows.length}）`,
                      },
                    ].map((option) => (
                      <button
                        key={option.label}
                        type="button"
                        aria-pressed={workbenchOnly === option.only}
                        data-testid={
                          option.only
                            ? "flow-source-filter-workbench"
                            : "flow-source-filter-all"
                        }
                        onClick={() => setWorkbenchOnly(option.only)}
                        className={`rounded-md border px-2 py-1 ${
                          workbenchOnly === option.only
                            ? "border-foreground text-foreground"
                            : "border-border text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        {option.label}
                      </button>
                    ))}
                    {workbench.error && (
                      <span role="alert" className="text-destructive">
                        工作台来源索引暂时无法读取，来源和影像信息不完整。
                      </span>
                    )}
                  </div>
                )}
              {isEmptyFolder === true ? (
                <EmptyFolder
                  setOpenModal={setNewProjectModal}
                  onNewFlow={startNewFlow}
                />
              ) : (
                <div className="flex h-full flex-col">
                  {isLoading ||
                  isEmptyFolder === null ||
                  (workbenchOnly && workbenchRows.loading) ? (
                    view === "grid" ? (
                      <div className="mt-4 grid grid-cols-1 gap-1 md:grid-cols-2 lg:grid-cols-3">
                        <ListSkeleton />
                        <ListSkeleton />
                      </div>
                    ) : (
                      <div className="mt-4 flex flex-col gap-1">
                        <ListSkeleton />
                        <ListSkeleton />
                      </div>
                    )
                  ) : flowType === "mcp" ? (
                    <CustomMcpServerTab folderName={folderName} />
                  ) : flowType === "deployments" ? (
                    <DeploymentsPage />
                  ) : flowType === "files" ? (
                    <ProjectFilesTab
                      projectId={folderId ?? myCollectionId ?? ""}
                    />
                  ) : workbenchOnly && listedFlows.length === 0 ? (
                    <div className="pt-24 text-center text-sm text-secondary-foreground">
                      没有匹配的工作台工作流。
                    </div>
                  ) : (flowType === "flows" || flowType === "components") &&
                    data &&
                    (workbenchOnly || data.pagination.total > 0) ? (
                    view === "grid" ? (
                      <div className="mt-4 grid grid-cols-1 gap-1 md:grid-cols-2 lg:grid-cols-3">
                        {listedFlows.map((flow, index) => (
                          <ListComponent
                            key={flow.id}
                            flowData={flow}
                            selected={selectedFlows.includes(flow.id)}
                            setSelected={(selected) =>
                              setSelectedFlow(selected, flow.id, index)
                            }
                            shiftPressed={isShiftPressed || isCtrlPressed}
                            source={
                              flowType === "flows"
                                ? workbench.sourceOf(flow)
                                : null
                            }
                          />
                        ))}
                      </div>
                    ) : (
                      <div className="mt-4 flex flex-col gap-1">
                        {listedFlows.map((flow, index) => (
                          <ListComponent
                            key={flow.id}
                            flowData={flow}
                            selected={selectedFlows.includes(flow.id)}
                            setSelected={(selected) =>
                              setSelectedFlow(selected, flow.id, index)
                            }
                            shiftPressed={isShiftPressed || isCtrlPressed}
                            source={
                              flowType === "flows"
                                ? workbench.sourceOf(flow)
                                : null
                            }
                          />
                        ))}
                      </div>
                    )
                  ) : (
                    <div className="pt-24 text-center text-sm text-secondary-foreground">
                      {t("home.flowTypeNotSupported", { flowType })}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
          {(flowType === "flows" || flowType === "components") &&
            !workbenchOnly &&
            !isLoading &&
            !isEmptyFolder &&
            data.pagination.total >= 10 && (
              <div className="flex justify-end px-3 py-4">
                <PaginatorComponent
                  pageIndex={data.pagination.page}
                  pageSize={data.pagination.size}
                  rowsCount={[12, 24, 48, 96]}
                  totalRowsCount={data.pagination.total}
                  paginate={handlePageChange}
                  pages={data.pagination.pages}
                  isComponent={flowType === "components"}
                />
              </div>
            )}
        </div>
      </div>

      <ModalsComponent
        openModal={newProjectModal}
        setOpenModal={setNewProjectModal}
        openDeleteFolderModal={false}
        setOpenDeleteFolderModal={() => {}}
        handleDeleteFolder={() => {}}
      />
    </CardsWrapComponent>
  );
};

export default HomePage;
