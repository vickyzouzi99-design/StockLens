"""Exercise ASGI routing, validation and JSON serialization without network access."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import app
from collect_data import atomic_json


async def post(path, payload):
    messages = []
    async def receive():
        return {"type": "http.request", "body": json.dumps(payload).encode(), "more_body": False}
    async def send(message):
        messages.append(message)
    await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
               "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(),
               "query_string": b"", "headers": [(b"content-type", b"application/json")],
               "client": ("127.0.0.1", 1), "server": ("test", 80), "root_path": ""}, receive, send)
    status = next(message["status"] for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return status, json.loads(body)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_requests_are_rejected_at_api_boundary(self):
        for body in [{"pe_max": -2}, {"pe_max": 20, "snapshot_id": "../latest"}, {"snapshot_id": "a"*32}]:
            status, _ = await post("/api/screen", body)
            self.assertEqual(status, 422)

    async def test_snapshot_selection_through_screen_and_compare_routes(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {
            'STOCKLENS_DATA_DIR': folder, 'STOCKLENS_SNAPSHOT': ''
        }):
            identity = "a"*32
            old = {"metadata": {"snapshot_id": identity}, "stocks": [{"thscode": "A", "pe_ttm": 25}]}
            atomic_json(Path(folder) / "history" / f"{identity}.json", old)
            atomic_json(Path(folder) / "stock_snapshot_latest.json", {
                "metadata": {"snapshot_id": "b"*32}, "stocks": [{"thscode": "A", "pe_ttm": 100}]})
            status, result = await post("/api/screen", {"pe_max": 30, "snapshot_id": identity})
            self.assertEqual(status, 200)
            self.assertEqual(result["summary"]["selected"], 1)
            status, result = await post("/api/compare", {
                "before": {"pe_max": 20}, "after": {"pe_max": 30}, "snapshot_id": identity})
            self.assertEqual(status, 200)
            self.assertEqual(result["changes"]["newly_selected"][0]["thscode"], "A")
            status, _ = await post("/api/screen", {"pe_max": 30, "snapshot_id": "c"*32})
            self.assertEqual(status, 409)
