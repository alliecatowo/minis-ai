from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def _load_main_module():
    module_name = "minis_mcp_main_under_test"
    if module_name in sys.modules:
        return sys.modules[module_name]

    main_path = Path(__file__).resolve().parents[1] / "main.py"
    spec = importlib.util.spec_from_file_location(module_name, main_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {main_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


main = _load_main_module()


class MinisMcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_mini_resolves_username_route(self):
        async def fake_request_json(method, path, **kwargs):
            self.assertEqual(method, "GET")
            self.assertEqual(path, "/minis/by-username/torvalds")
            self.assertFalse(kwargs)
            return {"id": "mini-123", "username": "torvalds"}

        original = main._request_json
        main._request_json = fake_request_json
        try:
            result = await main.get_mini.fn("torvalds")
        finally:
            main._request_json = original

        self.assertEqual(result["id"], "mini-123")

    async def test_get_mini_status_resolves_username_before_streaming(self):
        async def fake_request_json(method, path, **kwargs):
            self.assertEqual((method, path), ("GET", "/minis/by-username/torvalds"))
            return {"id": "5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd"}

        async def fake_stream_sse_events(method, path, **kwargs):
            self.assertEqual((method, path), ("GET", "/minis/5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd/status"))
            self.assertIn("timeout_seconds", kwargs)
            return [
                ("progress", '{"stage":"fetch","status":"started","message":"Started","progress":0.1}'),
                ("done", "Pipeline completed"),
            ]

        original_request = main._request_json
        original_stream = main._stream_sse_events
        main._request_json = fake_request_json
        main._stream_sse_events = fake_stream_sse_events
        try:
            result = await main.get_mini_status.fn("torvalds", timeout_seconds=15.0)
        finally:
            main._request_json = original_request
            main._stream_sse_events = original_stream

        self.assertEqual(
            result,
            [
                {
                    "event": "progress",
                    "stage": "fetch",
                    "status": "started",
                    "message": "Started",
                    "progress": 0.1,
                },
                {"event": "done", "data": "Pipeline completed"},
            ],
        )

    async def test_chat_with_mini_collects_conversation_and_chunks(self):
        async def fake_request_json(method, path, **kwargs):
            self.assertEqual((method, path), ("GET", "/minis/by-username/torvalds"))
            return {"id": "5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd"}

        async def fake_stream_sse_events(method, path, **kwargs):
            self.assertEqual((method, path), ("POST", "/minis/5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd/chat"))
            self.assertEqual(
                kwargs["json_body"],
                {
                    "message": "What do you think about Rust?",
                    "history": [],
                    "conversation_id": None,
                },
            )
            return [
                ("conversation_id", "conv-42"),
                ("chunk", "First "),
                ("chunk", "reply."),
            ]

        original_request = main._request_json
        original_stream = main._stream_sse_events
        main._request_json = fake_request_json
        main._stream_sse_events = fake_stream_sse_events
        try:
            result = await main.chat_with_mini.fn("torvalds", "What do you think about Rust?")
        finally:
            main._request_json = original_request
            main._stream_sse_events = original_stream

        self.assertEqual(
            result,
            {
                "mini_id": "5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd",
                "conversation_id": "conv-42",
                "response": "First reply.",
            },
        )


if __name__ == "__main__":
    unittest.main()
