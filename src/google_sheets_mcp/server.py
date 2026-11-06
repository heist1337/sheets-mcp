from __future__ import annotations

import hmac
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier


class LocalTokenVerifier(TokenVerifier):
    def __init__(self, token: str):
        super().__init__()
        self.token = token.encode()

    async def verify_token(self, token: str) -> AccessToken | None:
        if hmac.compare_digest(token.encode(), self.token):
            return AccessToken(token=token, client_id="google_sheets_mcp", scopes=[])
        return None


def create_server(*, token: str | None = None, service=None) -> FastMCP:
    mcp = FastMCP(
        "google_sheets_mcp",
        auth=LocalTokenVerifier(token) if token else None,
        mask_error_details=True,
        instructions="Read before writes and change only the explicitly requested target. On an uncertain write outcome, reconcile by reading before retry. Deletion is blocked.",
    )
    from .api import execute

    run = service or execute

    @mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True})
    def sheets_get(spreadsheet_id: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read spreadsheet metadata. Grid data requires explicit ranges; inspect before editing."""
        return run("get", spreadsheet_id, parameters or {})

    @mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True})
    def sheets_read(spreadsheet_id: str, range: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read one explicit A1 range; formulas are preserved by default. A range is not a full workbook."""
        return run("read", spreadsheet_id, {**(parameters or {}), "range": range})

    @mcp.tool(
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True}
    )
    def sheets_create(parameters: dict[str, Any]) -> dict[str, Any]:
        """Create a spreadsheet only on explicit user request. On timeout check for prior creation before retry."""
        return run("create", "", parameters)

    @mcp.tool(
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True}
    )
    def sheets_write(
        spreadsheet_id: str, range: str, values: list[list[Any]], parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Replace values in the approved A1 range. Default RAW; read back before retrying uncertain writes."""
        return run("write", spreadsheet_id, {**(parameters or {}), "range": range, "values": values})

    @mcp.tool(
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True}
    )
    def sheets_batch_update(
        spreadsheet_id: str, requests: list[dict[str, Any]], parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Apply approved formatting/structure operations. Deletion, clearing, grid shrinking and unknown requests are rejected. Other edits can still overwrite data."""
        return run("batch_update", spreadsheet_id, {**(parameters or {}), "requests": requests})

    return mcp
