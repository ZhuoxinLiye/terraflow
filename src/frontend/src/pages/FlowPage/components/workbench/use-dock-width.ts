import { useEffect, useRef, useState } from "react";

const WIDTH_KEY = "terraflow-workbench-dock-width";
const DEFAULT_WIDTH = 328;

export function useDockWidth(visible: boolean, sidebarOpen: boolean) {
  const dockRef = useRef<HTMLElement>(null);
  const dragRef = useRef<{ x: number; width: number } | null>(null);
  const [resizing, setResizing] = useState(false);
  const [preferredWidth, setPreferredWidth] = useState(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(WIDTH_KEY) ?? "null");
      if (typeof stored === "number" && Number.isFinite(stored)) {
        return Math.max(280, Math.min(900, stored));
      }
    } catch {
      // A blocked or invalid preference must not prevent opening the panel.
    }
    return DEFAULT_WIDTH;
  });
  const [maxWidth, setMaxWidth] = useState(900);
  const minWidth = Math.min(280, maxWidth);
  const clamp = (value: number) =>
    Math.round(Math.max(minWidth, Math.min(maxWidth, value)));
  const width = clamp(preferredWidth);

  useEffect(() => {
    if (!visible) return;
    const dock = dockRef.current;
    const parent = dock?.parentElement;
    const canvas = dock?.previousElementSibling;
    if (!dock || !parent || !canvas) return;
    const measure = () => {
      const parentRect = parent.getBoundingClientRect();
      const available = parentRect.right - canvas.getBoundingClientRect().left;
      // Keep canvas space on desktop; the existing mobile layout is an overlay.
      const limit =
        window.innerWidth < 768
          ? available - 16
          : available - Math.min(280, available * 0.35);
      setMaxWidth(Math.max(0, Math.min(900, Math.floor(limit))));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(parent);
    observer.observe(canvas);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [visible, sidebarOpen]);

  useEffect(() => {
    if (resizing) return;
    try {
      localStorage.setItem(WIDTH_KEY, JSON.stringify(preferredWidth));
    } catch {
      // Resizing still works when localStorage is unavailable.
    }
  }, [preferredWidth, resizing]);

  const stopResizing = () => {
    dragRef.current = null;
    setResizing(false);
  };

  return {
    dockRef,
    width,
    resizing,
    handleProps: {
      "aria-valuemin": minWidth,
      "aria-valuemax": maxWidth,
      "aria-valuenow": width,
      onPointerDown: (event: React.PointerEvent<HTMLDivElement>) => {
        if (event.button !== 0) return;
        event.preventDefault();
        event.stopPropagation();
        dragRef.current = { x: event.clientX, width };
        event.currentTarget.setPointerCapture(event.pointerId);
        event.currentTarget.focus();
        setResizing(true);
      },
      onPointerMove: (event: React.PointerEvent<HTMLDivElement>) => {
        const drag = dragRef.current;
        if (!drag) return;
        setPreferredWidth(clamp(drag.width + drag.x - event.clientX));
      },
      onPointerUp: stopResizing,
      onPointerCancel: stopResizing,
      onLostPointerCapture: stopResizing,
      onDoubleClick: () => setPreferredWidth(DEFAULT_WIDTH),
      onKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => {
        const step = event.shiftKey ? 50 : 10;
        const widths: Record<string, number> = {
          ArrowLeft: width + step,
          ArrowRight: width - step,
          Home: minWidth,
          End: maxWidth,
        };
        const next = widths[event.key];
        if (next === undefined) return;
        event.preventDefault();
        event.stopPropagation();
        setPreferredWidth(clamp(next));
      },
    },
  };
}
