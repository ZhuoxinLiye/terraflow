"""Synthetic temporary HTTP checks; no remote model or scientific data."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from detection_workspace import DetectionWorkspace, PREFIX


class DetectionWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        runtime = Path(self.tmp.name)
        self.workspace = DetectionWorkspace(SimpleNamespace(RUNTIME_DIR=runtime))
        self.calls = []
        self.workspace.sdk = lambda slug, inputs: self.calls.append((slug, inputs)) or {"success": True, "outputs": {"dataset_id": self.dataset}}
        self.dataset = "segearth:" + "a" * 32
        self.output = runtime / "outputs/synthetic-test"
        self.output.mkdir(parents=True)
        snapshot = self.output / "graph_annotations.json"
        snapshot.write_text('{"synthetic":true}')
        self.artifact = self.output / "synthetic.json"
        self.artifact.write_text('[{"synthetic":true}]')
        result_path = self.output / "earthmind_result.json"
        self.result = {"dataset_id": self.dataset, "snapshot_id": "sha256:" + hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                       "registered_at": "2026-11-06", "detection_count": 1,
                       "artifacts": {snapshot.name: str(snapshot), self.artifact.name: str(self.artifact)},
                       "artifact_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (snapshot, self.artifact)}}
        result_path.write_text(json.dumps(self.result))
        registry = runtime / "detection-datasets"
        registry.mkdir()
        (registry / ("a" * 32 + ".json")).write_text(json.dumps({
            "dataset_id": self.dataset, "snapshot_path": str(snapshot), "result_path": str(result_path),
            "snapshot_id": self.result["snapshot_id"], "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest()}))
        workspace = self.workspace

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def _send(self, status, body):
                self.send_response(status)
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())
            def do_GET(self):
                url = urlsplit(self.path)
                workspace.get(self, url.path, url.query)
            def do_POST(self):
                url = urlsplit(self.path)
                workspace.post(self, url.path, url.query)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(2)
        self.tmp.cleanup()

    def request(self, path, data=None, headers=None):
        req = Request(f"http://127.0.0.1:{self.server.server_port}" + PREFIX + path, data=data, headers=headers or {})
        try:
            with urlopen(req, timeout=5) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    def test_saved_history_and_graph_are_bound_to_registered_snapshot(self):
        status, body = self.request('/api/history')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['results'][0]['dataset_id'], self.dataset)
        status, _ = self.request('/api/graph?dataset_id=' + self.dataset)
        self.assertEqual(status, 200)
        self.assertEqual(self.calls[0], ('graph_query.query_nodes', {
            'dataset_id': self.dataset, 'snapshot_id': self.result['snapshot_id'], 'node_type': 'target', 'limit': 20}))

    def test_changed_artifact_and_metadata_are_rejected(self):
        self.artifact.write_text('tampered')
        self.assertEqual(self.request('/api/file?path=' + str(self.artifact))[0], 400)
        (self.output / 'earthmind_result.json').write_text('{}')
        self.assertEqual(self.request('/api/result?dataset_id=' + self.dataset)[0], 400)
        self.assertEqual(json.loads(self.request('/api/history')[1])['results'], [])

    def test_unregistered_file_and_invalid_dataset_cannot_be_used(self):
        unregistered = self.output / 'private.txt'
        unregistered.write_text('not registered')
        self.assertEqual(self.request('/api/file?path=' + str(unregistered))[0], 400)
        self.assertEqual(self.request('/api/file?path=/etc/passwd')[0], 400)
        self.assertEqual(self.request('/api/graph?dataset_id=../../etc/passwd')[0], 400)
        self.assertEqual(self.calls, [])

    def test_raw_upload_reaches_real_sdk_contract_once(self):
        job = 'b' * 32
        status, _ = self.request('/api/detect?filename=synthetic.png&job=' + job + '&batch=2', b'synthetic-image-bytes',
                                 {'X-SegEarth-Prompts': '%5B%5D'})
        self.assertEqual(status, 200)
        self.assertEqual(len(self.calls), 1)
        slug, inputs = self.calls[0]
        self.assertEqual(slug, 'segearth.detect')
        self.assertEqual(Path(inputs['input_path']).read_bytes(), b'synthetic-image-bytes')
        self.assertEqual(inputs['request_id'], job)
        self.assertEqual(inputs['prompt_categories'], [])
        self.assertEqual(self.request('/api/detect?filename=synthetic.png&job=' + job, b'duplicate')[0], 400)
        self.assertEqual(len(self.calls), 1)

    def test_failed_sdk_is_saved_as_failure_and_not_returned_as_empty_success(self):
        def fail(*args): raise ValueError('synthetic service unavailable')
        self.workspace.sdk = fail
        status, body = self.request('/api/detect?filename=synthetic.png&job=' + 'c' * 32, b'bytes')
        self.assertEqual(status, 400)
        self.assertIn('unavailable', json.loads(body)['error'])
        status, body = self.request('/api/progress?job=' + 'c' * 32)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['stage'], 'failed')


if __name__ == '__main__': unittest.main()
