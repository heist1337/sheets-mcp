"""Google SDK calls with the existing Sheets operation-level deletion guard."""

from __future__ import annotations

import os
import re
from typing import Any

import google.auth
import google_auth_httplib2
import httplib2
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Explicit Sheets v4 request allowlist. Unknown requests fail closed.
UPDATES = frozenset(
    """
addFilterView setBasicFilter repeatCell cancelDataSourceRefresh moveDimension mergeCells updateCells
addSheet insertComment updateNamedRange updateDimensionProperties updateSheetProperties updateBanding
updateDimensionGroup updateDataSource createDeveloperMetadata addTable insertRange updateSpreadsheetProperties
updateTable sortRange duplicateSheet updateChartSpec updateConditionalFormatRule autoResizeDimensions
addNamedRange addSlicer addDataSource updateFilterView randomizeRange setDataValidation updateDeveloperMetadata
updateEmbeddedObjectPosition updateEmbeddedObjectBorder addBanding addChart addDimensionGroup updateBorders
autoFill updateSlicerSpec pasteData refreshDataSource findReplace addProtectedRange insertDimension
addConditionalFormatRule unmergeCells addCommentReply copyPaste duplicateFilterView updateCommentPost
updateProtectedRange appendCells appendDimension textToColumns
""".split()
)
PARAMETERS = {
    "create": {"properties", "sheets", "namedRanges", "developerMetadata", "dataSources"},
    "get": {"ranges", "includeGridData", "fields"},
    "read": {"range", "majorDimension", "valueRenderOption", "dateTimeRenderOption"},
    "write": {
        "range",
        "values",
        "majorDimension",
        "valueInputOption",
        "includeValuesInResponse",
        "responseValueRenderOption",
        "responseDateTimeRenderOption",
    },
    "batch_update": {"requests", "includeSpreadsheetInResponse", "responseRanges", "responseIncludeGridData"},
}
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def validate(operation: str, spreadsheet_id: str, parameters: dict[str, Any]) -> None:
    if operation not in PARAMETERS or not isinstance(parameters, dict) or parameters.keys() - PARAMETERS[operation]:
        raise ValueError("unsupported_sheets_operation_or_parameters")
    if operation != "create" and not re.fullmatch(r"[A-Za-z0-9_-]+", spreadsheet_id):
        raise ValueError("raw_spreadsheet_id_required")
    if operation in {"read", "write"} and not isinstance(parameters.get("range"), str):
        raise ValueError("explicit_range_required")
    if operation in {"read", "write"} and not parameters["range"].strip():
        raise ValueError("explicit_range_required")
    if operation == "get" and parameters.get("includeGridData") and not parameters.get("ranges"):
        raise ValueError("grid_data_requires_explicit_ranges")
    if operation == "write":
        rows = parameters.get("values")
        if not isinstance(rows, list) or not all(isinstance(row, list) for row in rows):
            raise ValueError("values_matrix_required")
        if parameters.get("valueInputOption", "RAW") not in {"RAW", "USER_ENTERED"}:
            raise ValueError("invalid_value_input_option")
    if operation != "batch_update":
        return
    requests = parameters.get("requests")
    if not isinstance(requests, list) or not requests:
        raise ValueError("nonempty_requests_required")
    if parameters.get("responseIncludeGridData") and not parameters.get("responseRanges"):
        raise ValueError("response_grid_data_requires_explicit_ranges")
    for request in requests:
        if not isinstance(request, dict) or len(request) != 1 or not request.keys() <= UPDATES:
            raise ValueError("deletion_or_unsupported_request_forbidden")
        name, body = next(iter(request.items()))
        if not isinstance(body, dict):
            raise ValueError("invalid_request_body")
        if name == "updateSheetProperties":

            def normalize(value):
                return value.replace("_", "").lower()

            properties = body.get("properties", {})
            if not isinstance(properties, dict):
                raise ValueError("invalid_sheet_properties")
            grids = [value for key, value in properties.items() if normalize(key) == "gridproperties"]
            fields = [normalize(field.strip()) for field in str(body.get("fields", "")).split(",")]
            allowed = {
                "frozenrowcount",
                "frozencolumncount",
                "hidegridlines",
                "rowgroupcontrolafter",
                "columngroupcontrolafter",
            }
            if any(
                not isinstance(grid, dict) or any(normalize(key) in {"rowcount", "columncount"} for key in grid)
                for grid in grids
            ) or any(
                any(char in field for char in "*()")
                or (field.startswith("gridproperties") and field.removeprefix("gridproperties.") not in allowed)
                for field in fields
            ):
                raise ValueError("grid_resize_forbidden_use_append_or_insert_dimension")


def credentials():
    path = os.environ.get("GOOGLE_OAUTH_TOKEN_FILE")
    if path:
        return Credentials.from_authorized_user_file(path, scopes=SCOPES)
    return google.auth.default(scopes=SCOPES)[0]


def execute(operation: str, spreadsheet_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Validate before loading credentials; SDK owns auth, encoding and API discovery."""
    validate(operation, spreadsheet_id, parameters)
    http = httplib2.Http(timeout=60)
    http.follow_redirects = False
    authorized = google_auth_httplib2.AuthorizedHttp(credentials(), http=http)
    service = build("sheets", "v4", http=authorized, cache_discovery=False)
    try:
        sheets = service.spreadsheets()
        options = dict(parameters)
        if operation == "create":
            request = sheets.create(body=options)
        elif operation == "get":
            request = sheets.get(spreadsheetId=spreadsheet_id, **options)
        elif operation == "batch_update":
            request = sheets.batchUpdate(spreadsheetId=spreadsheet_id, body=options)
        elif operation == "read":
            options.setdefault("valueRenderOption", "FORMULA")
            request = sheets.values().get(spreadsheetId=spreadsheet_id, **options)
        else:
            body = {"values": options.pop("values"), "majorDimension": options.pop("majorDimension", "ROWS")}
            options.setdefault("valueInputOption", "RAW")
            request = sheets.values().update(spreadsheetId=spreadsheet_id, body=body, **options)
        # No automatic retries: a write timeout has an unknown outcome.
        return request.execute(num_retries=0)
    except HttpError as error:
        raise RuntimeError(f"google_sheets_api_error:{error.resp.status}") from None
    finally:
        service.close()


def authorize(client_secrets: str, token_file: str) -> None:
    """Use Google's installed-app flow; keep refresh credentials in a private file."""
    from pathlib import Path

    from google_auth_oauthlib.flow import InstalledAppFlow

    path = Path(token_file).expanduser()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flow = InstalledAppFlow.from_client_secrets_file(client_secrets, SCOPES)
    creds = flow.run_local_server(port=0, open_browser=False)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(creds.to_json())
