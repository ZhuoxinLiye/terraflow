"""Read existing workspace catalog records without generating or transforming data."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def search_remote_sensing_data(query: str = "", *, include_test_data: bool = False, limit: int = 12) -> dict:
    """Search existing local remote-sensing data by ID, place, date, sensor or type.

    Use an empty query to list available data. Copy returned IDs/paths exactly;
    scene_id is usable by SceneInput only when scene_input_available is true.
    Other assets can be passed by path to compatible Terrabox tools. Band and
    scale requirements still apply. Set include_test_data only when the user
    explicitly requests synthetic/test fixtures. This tool never creates data.
    """
    runtime = os.getenv("TERRAFLOW_WATER_RUNTIME_DIR")
    if not runtime:
        return {"error": "Workspace data runtime is not configured", "items": []}
    root = Path(runtime)
    scenes = _read(root / "scene-index.json")
    records = []
    for scene_id, scene in scenes.items():
        if not isinstance(scene, dict) or not scene.get("path"):
            continue
        if not include_test_data and scene.get("category") in {"synthetic", "test"}:
            continue
        path = str(scene["path"])
        available = Path(path).is_file()
        records.append(
            {
                "id": scene_id,
                "scene_id": scene_id,
                "scene_input_available": available,
                "available": available,
                "source": "scene-index",
                **scene,
            }
        )
    for item_path in sorted((root / "catalog" / "collections").glob("*/items/*.json")):
        item = _read(item_path)
        props = item.get("properties") or {}
        collection = _read(item_path.parent.parent / "collection.json")
        if not include_test_data and (
            props.get("workspace:origin") in {"synthetic", "test"}
            or props.get("workspace:audience") in {"developer", "test"}
        ):
            continue
        assets = []
        for key, asset in (item.get("assets") or {}).items():
            if not isinstance(asset, dict) or "data" not in asset.get("roles", ["data"]):
                continue
            href = asset.get("href", "")
            path = Path(href) if href else None
            if path and not path.is_absolute():
                path = item_path.parent / path
            assets.append(
                {**asset, "key": key, "path": str(path) if path else "", "available": bool(path and path.is_file())}
            )
        records.append(
            {
                "id": item.get("id"),
                "collection": item.get("collection"),
                "collection_title": collection.get("title"),
                "source": "STAC Item",
                "properties": props,
                "assets": assets,
                "bbox": item.get("bbox"),
                "scene_input_available": False,
                "available": any(a["available"] for a in assets),
            }
        )
    # Literal substring search avoids inventing a semantic match. The model can
    # retry a broader term/empty query when there are no matches.
    terms = query.casefold().split()
    matches = [r for r in records if all(t in json.dumps(r, ensure_ascii=False).casefold() for t in terms)]
    return {
        "items": matches[: max(1, min(limit, 30))],
        "matched": len(matches),
        "total_visible": len(records),
        "test_data_included": include_test_data,
        "note": (
            "Catalog declarations and existing files; availability is not scientific validation. "
            "No downloads or conversions performed."
        ),
    }
