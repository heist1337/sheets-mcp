from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx2
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from fastmcp.utilities.asgi_transport import StreamingASGITransport

from google_sheets_mcp import api as sheets
from google_sheets_mcp.server import create_server

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "synthetic-mcp-token-not-an-actual-credential"


class SheetsGuardTest(unittest.TestCase):
    def test_deletion_and_implicit_grid_resize_never_load_credentials(self):
        denied = [
            {name: {}}
            for name in (
                "deleteSheet",
                "deleteDimension",
                "deleteRange",
                "deleteChart",
                "cutPaste",
                "deleteDuplicates",
                "unknownFutureRequest",
                "clearBasicFilter",
            )
        ]
        denied += [
            {"updateSheetProperties": body}
            for body in (
                {"properties": {"gridProperties": {"rowCount": 1}}, "fields": "gridProperties.rowCount"},
                {"properties": {"grid_properties": {"column_count": 1}}, "fields": "grid_properties.column_count"},
                {"properties": {}, "fields": "*"},
                {"properties": {}, "fields": "gridProperties"},
                {"properties": {}, "fields": "gridProperties(rowCount)"},
            )
        ]
        with patch.object(sheets, "credentials") as credentials:
            for body in denied:
                with self.subTest(body=body), self.assertRaises(ValueError):
                    sheets.execute("batch_update", "sample-id", {"requests": [body]})
            credentials.assert_not_called()

    def test_bounded_reads_and_parameter_overrides_fail_before_auth(self):
        cases = [
            ("read", {"range": ""}),
            ("read", {"range": "A1", "url": "http://elsewhere"}),
            ("get", {"includeGridData": True}),
            ("write", {"range": "A1", "values": [1]}),
            ("batch_update", {"requests": []}),
        ]
        with patch.object(sheets, "credentials") as credentials:
            for operation, params in cases:
                with self.subTest(operation=operation, params=params), self.assertRaises(ValueError):
                    sheets.execute(operation, "sample-id", params)
            credentials.assert_not_called()

    def test_sdk_write_uses_exact_target_no_retry_and_no_redirect(self):
        api = Mock()
        api.spreadsheets.return_value.values.return_value.update.return_value.execute.return_value = {"updatedCells": 1}
        with (
            patch.object(sheets, "credentials", return_value=Mock()),
            patch.object(sheets, "build", return_value=api) as build,
        ):
            result = sheets.execute("write", "sample-id", {"range": "Лист 1!A1", "values": [["=1+1"]]})
        self.assertEqual(result, {"updatedCells": 1})
        call = api.spreadsheets.return_value.values.return_value.update
        call.assert_called_once_with(
            spreadsheetId="sample-id",
            body={"values": [["=1+1"]], "majorDimension": "ROWS"},
            range="Лист 1!A1",
            valueInputOption="RAW",
        )
        call.return_value.execute.assert_called_once_with(num_retries=0)
        self.assertFalse(build.call_args.kwargs["http"].http.follow_redirects)
        self.assertEqual(build.call_args.kwargs["http"].http.timeout, 60)
        api.close.assert_called_once()


class MCPTest(unittest.IsolatedAsyncioTestCase):
    async def test_sheets_catalog_and_real_sdk_boundary(self):
        with patch.object(sheets, "credentials") as credentials:
            async with Client(create_server()) as client:
                tools = await client.list_tools()
                self.assertEqual(
                    {t.name for t in tools},
                    {"sheets_get", "sheets_read", "sheets_create", "sheets_write", "sheets_batch_update"},
                )
                self.assertNotIn("token", json.dumps([t.input_schema for t in tools]))
                with self.assertRaises(ToolError):
                    await client.call_tool(
                        "sheets_batch_update",
                        {"spreadsheet_id": "sample", "requests": [{"deleteSheet": {"sheetId": 0}}]},
                    )
            credentials.assert_not_called()

    async def test_http_auth_and_native_transport(self):
        mcp = create_server(token=TOKEN, service=lambda *args: {"sheets": []})
        app = mcp.http_app(path="/mcp/")
        async with app.lifespan(app):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app), base_url="http://test") as http:
                self.assertEqual((await http.post("/mcp/", json={})).status_code, 401)
                self.assertEqual(
                    (await http.post("/mcp/", json={}, headers={"Authorization": "Bearer invalid"})).status_code, 401
                )
            transport = StreamableHttpTransport(
                "http://test/mcp/",
                auth=TOKEN,
                httpx_client_factory=lambda **kwargs: httpx2.AsyncClient(
                    transport=StreamingASGITransport(app), **kwargs
                ),
            )
            async with Client(transport) as client:
                self.assertEqual(
                    (await client.call_tool("sheets_get", {"spreadsheet_id": "sample"})).data, {"sheets": []}
                )
