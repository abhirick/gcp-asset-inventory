#!/usr/bin/env python3
"""
GCP Project Asset Inventory Exporter

Features:
- ADC authentication
- Project-level Cloud Asset Inventory
- Asset type filtering (env configurable)
- JSON / CSV / HTML export
- Structured logging
- Streaming (handles large inventories)

Env vars:
    GCP_PROJECT_ID=my-project
    GCP_ASSET_TYPES=compute.googleapis.com/Instance,storage.googleapis.com/Bucket
    EXPORT_FORMAT=json|csv|html
    EXPORT_PATH=assets.json
"""

from __future__ import annotations

import csv
import html
import json
import logging
import os
import sys
from typing import Iterable, Iterator, Optional

from google.cloud import asset_v1

# ------------------------------------------------------------------------------
# Config
# ------------------------------------------------------------------------------

PROJECT_ENV = "GCP_PROJECT_ID"
ASSET_TYPES_ENV = "GCP_ASSET_TYPES"
EXPORT_FORMAT_ENV = "EXPORT_FORMAT"
EXPORT_PATH_ENV = "EXPORT_PATH"

DEFAULT_EXPORT_FORMAT = "json"
DEFAULT_EXPORT_PATH = "gcp_assets.json"

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("gcp_asset_inventory")

# ------------------------------------------------------------------------------
# Env helpers
# ------------------------------------------------------------------------------


def get_project_parent() -> str:
    project_id = os.getenv(PROJECT_ENV)
    if not project_id:
        raise ValueError(f"{PROJECT_ENV} not set")
    return f"projects/{project_id}"


def get_asset_types() -> Optional[list[str]]:
    raw = os.getenv(ASSET_TYPES_ENV)
    if not raw:
        return None
    return [t.strip() for t in raw.split(",") if t.strip()]


def get_export_config() -> tuple[str, str]:
    fmt = os.getenv(EXPORT_FORMAT_ENV, DEFAULT_EXPORT_FORMAT).lower()
    path = os.getenv(EXPORT_PATH_ENV, DEFAULT_EXPORT_PATH)

    if fmt not in {"json", "csv", "html"}:
        raise ValueError("EXPORT_FORMAT must be json, csv, or html")

    return fmt, path


# ------------------------------------------------------------------------------
# Asset listing
# ------------------------------------------------------------------------------


def list_assets(
    parent: str,
    asset_types: Optional[list[str]] = None,
    page_size: int = 500,
) -> Iterator[asset_v1.Asset]:
    client = asset_v1.AssetServiceClient()

    request = asset_v1.ListAssetsRequest(
        parent=parent,
        asset_types=asset_types or [],
        content_type=asset_v1.ContentType.RESOURCE,
        page_size=page_size,
    )

    pager = client.list_assets(request=request)

    for asset in pager:
        yield asset


# ------------------------------------------------------------------------------
# Normalize
# ------------------------------------------------------------------------------


def normalize_asset(asset: asset_v1.Asset) -> dict:
    resource = asset.resource

    return {
        "name": asset.name,
        "asset_type": asset.asset_type,
        "location": getattr(resource, "location", None),
        "project": asset.ancestors[0] if asset.ancestors else None,
    }


# ------------------------------------------------------------------------------
# Exporters
# ------------------------------------------------------------------------------


def export_json(path: str, rows: Iterable[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            json.dump(row, f)
            f.write("\n")


def export_csv(path: str, rows: Iterable[dict]) -> None:
    rows = list(rows)
    if not rows:
        return

    fieldnames = rows[0].keys()

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def export_html(path: str, rows: Iterable[dict]) -> None:
    rows = list(rows)

    def esc(v: Optional[str]) -> str:
        return html.escape(str(v)) if v is not None else ""

    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>GCP Asset Inventory</title>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial;
    margin: 40px;
    background: #f5f7fb;
}}
h1 {{
    margin-bottom: 10px;
}}
.summary {{
    margin-bottom: 20px;
    color: #444;
}}
table {{
    border-collapse: collapse;
    width: 100%;
    background: white;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
}}
th, td {{
    padding: 10px 12px;
    border-bottom: 1px solid #eee;
    text-align: left;
}}
th {{
    background: #fafbff;
    cursor: pointer;
    position: sticky;
    top: 0;
}}
tr:hover {{
    background: #f1f5ff;
}}
.search {{
    margin-bottom: 15px;
}}
input {{
    padding: 8px 10px;
    width: 320px;
    border: 1px solid #ddd;
    border-radius: 6px;
}}
</style>
<script>
function sortTable(n) {{
    var table = document.getElementById("assetTable");
    var rows = Array.from(table.rows).slice(1);
    var asc = table.getAttribute("data-sort") !== "asc";
    rows.sort((a,b)=>a.cells[n].innerText.localeCompare(b.cells[n].innerText));
    if(!asc) rows.reverse();
    rows.forEach(r=>table.appendChild(r));
    table.setAttribute("data-sort", asc ? "asc":"desc");
}}

function filterTable() {{
    var input = document.getElementById("searchInput").value.toLowerCase();
    var rows = document.querySelectorAll("#assetTable tbody tr");
    rows.forEach(r=>{{
        r.style.display = r.innerText.toLowerCase().includes(input) ? "" : "none";
    }});
}}
</script>
</head>
<body>

<h1>GCP Asset Inventory</h1>
<div class="summary">Total assets: {total}</div>

<div class="search">
<input id="searchInput" onkeyup="filterTable()" placeholder="Search assets...">
</div>

<table id="assetTable">
<thead>
<tr>
<th onclick="sortTable(0)">Name</th>
<th onclick="sortTable(1)">Type</th>
<th onclick="sortTable(2)">Location</th>
<th onclick="sortTable(3)">Project</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</body>
</html>
"""

    row_html_parts = []
    for r in rows:
        row_html_parts.append(
            "<tr>"
            f"<td>{esc(r.get('name'))}</td>"
            f"<td>{esc(r.get('asset_type'))}</td>"
            f"<td>{esc(r.get('location'))}</td>"
            f"<td>{esc(r.get('project'))}</td>"
            "</tr>"
        )

    final_html = html_template.format(
        total=len(rows),
        rows_html="\n".join(row_html_parts),
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(final_html)


# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------


def main() -> int:
    try:
        parent = get_project_parent()
        asset_types = get_asset_types()
        export_format, export_path = get_export_config()

        logger.info("Project: %s", parent)
        logger.info("Filter asset types: %s", asset_types or "ALL")
        logger.info("Export: %s -> %s", export_format, export_path)

        def row_stream() -> Iterator[dict]:
            count = 0
            for asset in list_assets(parent, asset_types):
                count += 1
                yield normalize_asset(asset)
            logger.info("Assets processed: %s", count)

        if export_format == "json":
            export_json(export_path, row_stream())
        elif export_format == "csv":
            export_csv(export_path, row_stream())
        else:
            export_html(export_path, row_stream())

        logger.info("Export complete")
        return 0

    except Exception as exc:  # noqa: BLE001
        logger.exception("Fatal error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())