"""Authenticated workspace routes for the existing SegEarth UI and SDK tools."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
from urllib.parse import parse_qs, unquote, urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
UI = ROOT / "detection_ui"
PREFIX = "/api/water-demo/detection"


class DetectionWorkspace:
    def __init__(self, api):
        self.api = api
        self.runtime = api.RUNTIME_DIR.resolve()
        self.jobs = self.runtime / "detection-jobs"
        self.jobs.mkdir(parents=True, exist_ok=True)

    def atomic(self, path, data):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def remote(self, path):
        config_path = Path(os.environ.get("SEGEARTH_CONFIG_FILE", str(Path.home() / ".config/agent-workspace/segearth.json")))
        config = json.loads(config_path.read_text()) if config_path.is_file() else {}
        base = os.environ.get("SEGEARTH_SERVICE_URL", config.get("service_url", ""))
        token = os.environ.get("SEGEARTH_SERVICE_TOKEN", "")
        if not token and config.get("service_token_file"):
            token = Path(config["service_token_file"]).read_text().strip()
        if not base or not token:
            raise ValueError("检测服务尚未连接；已保存结果仍可查看。")
        with urlopen(Request(base.rstrip("/") + path, headers={"Authorization": "Bearer " + token}), timeout=10) as response:
            return json.load(response)

    def sdk(self, slug, inputs):
        key_path = Path(os.environ.get("TERRABOX_API_KEY_FILE", "/tmp/terrabox-api-key"))
        key = key_path.read_text().strip()
        base = os.environ.get("TERRABOX_BASE_URL", "http://127.0.0.1:8010")
        request = Request(base + "/v1/sdk/tools/" + slug + "/execute", data=json.dumps({"inputs": inputs}).encode(),
                          headers={"Content-Type": "application/json", "X-API-Key": key})
        with urlopen(request, timeout=float(os.environ.get("SEGEARTH_HTTP_TIMEOUT", "7500"))) as response:
            result = json.load(response)
        if not result.get("success"):
            raise ValueError(str(result.get("error") or "工具执行失败，未生成可交付结果。"))
        return result

    def record(self, dataset_id):
        if not re.fullmatch(r"segearth:[a-f0-9]{32}", dataset_id):
            raise ValueError("无效的检测数据集编号")
        index = json.loads((self.runtime / "detection-datasets" / (dataset_id.split(":")[1] + ".json")).read_text())
        path = Path(index["result_path"]).resolve()
        if not path.is_relative_to(self.runtime / "outputs"):
            raise ValueError("检测结果路径不在运行目录内")
        if hashlib.sha256(path.read_bytes()).hexdigest() != index.get("result_sha256"):
            raise ValueError("检测结果元数据完整性核查失败")
        result = json.loads(path.read_text())
        snapshot = Path(result["artifacts"]["graph_annotations.json"]).resolve()
        if (not snapshot.is_relative_to(path.parent) or str(snapshot) != index["snapshot_path"]
                or result["dataset_id"] != dataset_id or result["snapshot_id"] != index["snapshot_id"]):
            raise ValueError("检测结果来源不一致")
        if "sha256:" + hashlib.sha256(snapshot.read_bytes()).hexdigest() != result["snapshot_id"]:
            raise ValueError("检测图谱快照已改变，不能继续使用")
        return result

    def history(self):
        results = []
        for path in (self.runtime / "detection-datasets").glob("*.json"):
            try:
                value = self.record("segearth:" + path.stem)
                results.append({key: value.get(key) for key in ("dataset_id", "snapshot_id", "detection_count", "class_counts", "registered_at", "origin", "execution_id")})
            except (ValueError, OSError, KeyError):
                continue
        return sorted(results, key=lambda row: row.get("registered_at", ""), reverse=True)

    def send_file(self, handler, path, *, download=False):
        handler.send_response(200)
        handler.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        handler.send_header("Content-Length", str(path.stat().st_size))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        if download:
            handler.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        handler.end_headers()
        with path.open("rb") as stream:
            shutil.copyfileobj(stream, handler.wfile)

    def get(self, handler, path, query):
        if not path.startswith(PREFIX + "/"):
            return False
        endpoint = path[len(PREFIX):]
        args = parse_qs(query)
        try:
            static = {"/ui": "index.html", "/ui/index.html": "index.html", "/ui/app.js": "app.js",
                      "/ui/styles.css": "styles.css", "/ui/integration.js": "integration.js"}
            if endpoint in static:
                self.send_file(handler, UI / static[endpoint])
            elif endpoint == "/health":
                handler._send(200, self.remote("/health"))
            elif endpoint == "/api/prompts":
                handler._send(200, json.loads((UI / "default_prompts.json").read_text()))
            elif endpoint == "/api/history":
                handler._send(200, {"results": self.history()})
            elif endpoint == "/api/result":
                handler._send(200, self.record(args.get("dataset_id", [""])[0]))
            elif endpoint == "/api/progress":
                job = args.get("job", [""])[0]
                if not re.fullmatch(r"[a-f0-9]{32}", job):
                    raise ValueError("无效任务编号")
                jobpath = self.jobs / (job + ".json")
                state = json.loads(jobpath.read_text()) if jobpath.exists() else {"stage": "waiting"}
                handler._send(200, state if state.get("stage") == "failed" else self.remote("/api/progress?" + urlencode({"job": job})))
            elif endpoint == "/api/graph":
                result = self.record(args.get("dataset_id", [""])[0])
                handler._send(200, self.sdk("graph_query.query_nodes", {"dataset_id": result["dataset_id"], "snapshot_id": result["snapshot_id"], "node_type": "target", "limit": 20}))
            elif endpoint == "/api/file":
                path = Path(args.get("path", [""])[0]).resolve()
                if not path.is_relative_to(self.runtime / "outputs"):
                    raise ValueError("产物路径不在运行目录内")
                result = json.loads((path.parent / "earthmind_result.json").read_text())
                result = self.record(result["dataset_id"])
                if result["artifacts"].get(path.name) != str(path):
                    raise ValueError("文件未登记为本次检测产物")
                h = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        h.update(block)
                if h.hexdigest() != result["artifact_sha256"].get(path.name):
                    raise ValueError("检测产物完整性核查失败")
                self.send_file(handler, path, download=args.get("download") == ["1"])
            else:
                handler._send(404, {"error": "检测接口不存在"})
        except (ValueError, OSError, KeyError) as exc:
            handler._send(400, {"error": str(exc)[:400]})
        return True

    def post(self, handler, path, query):
        if path != PREFIX + "/api/detect":
            return False
        job = None
        try:
            args = parse_qs(query)
            job, filename = args.get("job", [""])[0], args.get("filename", [""])[0]
            if not re.fullmatch(r"[a-f0-9]{32}", job):
                raise ValueError("无效任务编号")
            suffix = Path(filename).suffix.lower()
            length = int(handler.headers.get("Content-Length", "0"))
            if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"} or not 0 < length <= 100 * 1024 * 1024:
                raise ValueError("请选择100 MB以内的受支持影像")
            batch = int(args.get("batch", ["2"])[0])
            if batch < 1:
                raise ValueError("每批切片数必须为正整数")
            upload = self.runtime / "uploads/detection" / job
            upload.mkdir(parents=True, exist_ok=False)
            image = upload / ("input" + suffix)
            with image.open("xb") as stream:
                remaining = length
                while remaining:
                    chunk = handler.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("影像上传不完整")
                    stream.write(chunk)
                    remaining -= len(chunk)
            self.atomic(self.jobs / (job + ".json"), {"stage": "uploading", "job": job})
            inputs = {"input_path": str(image), "window_batch_size": batch, "request_id": job}
            custom = handler.headers.get("X-SegEarth-Prompts")
            if custom:
                if len(custom) > 60000:
                    raise ValueError("类别配置过大")
                inputs["prompt_categories"] = json.loads(unquote(custom))
            response = self.sdk("segearth.detect", inputs)
            result = response["outputs"]
            self.atomic(self.jobs / (job + ".json"), {"stage": "completed", "job": job, "dataset_id": result["dataset_id"]})
            handler._send(200, result)
        except (ValueError, OSError, KeyError) as exc:
            handler.close_connection = True
            if job and re.fullmatch(r"[a-f0-9]{32}", job):
                self.atomic(self.jobs / (job + ".json"), {"stage": "failed", "job": job, "error": str(exc)[:400]})
            handler._send(400, {"error": str(exc)[:400]})
        return True
