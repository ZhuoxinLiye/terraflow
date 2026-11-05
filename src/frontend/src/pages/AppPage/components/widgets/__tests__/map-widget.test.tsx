import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { WidgetContentProps } from "@/types/appPage/widget";
import { MapWidget } from "../map-widget";

const mockMaps: any[] = [];
const mockSetWorkerUrl = jest.fn();
jest.mock(
  "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url",
  () => "synthetic-bundled-worker-url",
  { virtual: true },
);
jest.mock(
  "maplibre-gl",
  () => ({
    Map: jest.fn((options) => {
      const sources = new Set<string>();
      const events: Record<string, (event?: unknown) => void> = {};
      const map = {
        options,
        events,
        addControl: jest.fn(),
        on: jest.fn((event, callback) => {
          events[event] = callback;
        }),
        addSource: jest.fn((id) => {
          sources.add(id);
        }),
        addLayer: jest.fn(),
        fitBounds: jest.fn(),
        getSource: jest.fn((id) => sources.has(id)),
        isSourceLoaded: jest.fn(() => true),
        queryRenderedFeatures: jest.fn(() => [{}]),
        remove: jest.fn(),
      };
      mockMaps.push(map);
      return map;
    }),
    AttributionControl: jest.fn(),
    setWorkerUrl: mockSetWorkerUrl,
  }),
  { virtual: true },
);
jest.mock("../../../utils/file-ref", () => ({
  useWidgetFileBytes: () => ({ data: undefined, status: "idle" }),
}));

// Synthetic geometry only: this verifies rendering availability, not geography.
const geojson = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { synthetic: true },
      geometry: { type: "Point", coordinates: [0, 0] },
    },
  ],
};
const props = {
  output: { type: "object", message: geojson },
} as WidgetContentProps;

beforeEach(() => {
  mockMaps.length = 0;
  mockSetWorkerUrl.mockClear();
});

it("shows input geometry without requesting an online basemap or waiting for tile load", async () => {
  render(<MapWidget {...props} />);
  await waitFor(() => expect(mockMaps).toHaveLength(1));
  const map = mockMaps[0];
  expect(mockSetWorkerUrl).toHaveBeenCalledWith("synthetic-bundled-worker-url");
  expect(map.options.style.sources).toEqual({});
  expect(map.events.load).toBeUndefined();
  act(() => {
    map.events["style.load"]();
    map.events.render();
  });
  expect(map.addSource).toHaveBeenCalledWith("widget-data", {
    type: "geojson",
    data: geojson,
  });
  expect(map.fitBounds).toHaveBeenCalled();
  expect(screen.getByTestId("map-widget-canvas")).toHaveAttribute(
    "data-geometry-ready",
    "true",
  );
  expect(screen.getByTestId("map-widget-canvas")).toHaveAttribute(
    "data-rendered-feature-count",
    "1",
  );
});

it("keeps local geometry available when the optional online basemap fails", async () => {
  render(<MapWidget {...props} />);
  await waitFor(() => expect(mockMaps).toHaveLength(1));
  fireEvent.click(screen.getByRole("checkbox"));
  await waitFor(() => expect(mockMaps).toHaveLength(2));
  const map = mockMaps[1];
  expect(map.options.style.sources.osm).toBeDefined();
  // There is deliberately no global load event: tiles never become ready.
  act(() => {
    map.events["style.load"]();
    map.events.error({
      sourceId: "osm",
      error: new Error("Synthetic basemap network failure"),
    });
    map.events.render();
  });
  expect(map.addSource).toHaveBeenCalledWith("widget-data", {
    type: "geojson",
    data: geojson,
  });
  expect(screen.getByRole("status")).toBeInTheDocument();
  expect(screen.getByTestId("map-widget-canvas")).toHaveAttribute(
    "data-rendered-feature-count",
    "1",
  );
});

it("removes the map when navigating away", async () => {
  const view = render(<MapWidget {...props} />);
  await waitFor(() => expect(mockMaps).toHaveLength(1));
  view.unmount();
  expect(mockMaps[0].remove).toHaveBeenCalledTimes(1);
});
