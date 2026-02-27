#!/usr/bin/env python3
"""
Export GCP Asset Inventory to GCS using Cloud Asset Inventory API (long-running operation).

Why ExportAssets:
- Designed for inventory pulls (project now, org later)
- Server-side export, scalable
- Outputs NDJSON to GCS (recommended for big exports)

Install:
  pip install google-cloud-asset google-api-core

Auth (ADC supported):
  gcloud auth application-default login
  OR
  export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

IMPORTANT IAM:
1) Caller (your ADC identity) must have permission to call exportAssets on the scope.
2) Cloud Asset service agent must be able to write to the destination bucket:
     service-PROJECT_NUMBER@gcp-sa-cloudasset.iam.gserviceaccount.com
   Grant on the destination bucket: roles/storage.objectCreator
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from typing import Iterable, Optional

from google.api_core import exceptions, retry
from google.api_core.client_options import ClientOptions
from google.cloud import asset_v1


LOG = logging.getLogger("asset_export")


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def normalise_gcs_uri(base_gcs_uri: str, parent: str) -> str:
    """
    If you pass a prefix (gs://bucket/path/), we create a unique file name.
    If you pass a full object (gs://bucket/path/file.ndjson), we use it as-is.
    """
    if not base_gcs_uri.startswith("gs://"):
        raise ValueError("gcs_uri must start with gs://")

    is_prefix = base_gcs_uri.endswith("/")
    if not is_prefix:
        return base_gcs_uri

    safe_parent = parent.replace("/", "_").replace(":", "_")
    return f"{base_gcs_uri}{safe_parent}_{utc_stamp()}.ndjson"


def build_client(
    use_rest: bool = True,
    api_endpoint: Optional[str] = None,  # e.g. "restricted.googleapis.com" (VPC-SC)
) -> asset_v1.AssetServiceClient:
    client_kwargs = {}
    if use_rest:
        client_kwargs["transport"] = "rest"
    if api_endpoint:
        client_kwargs["client_options"] = ClientOptions(api_endpoint=api_endpoint)
    return asset_v1.AssetServiceClient(**client_kwargs)


def export_assets_to_gcs(
    *,
    parent: str,
    gcs_uri: str,
    asset_types: Optional[Iterable[str]] = None,
    content_type: asset_v1.ContentType = asset_v1.ContentType.RESOURCE,
    use_rest: bool = True,
    api_endpoint: Optional[str] = None,
    per_request_timeout_s: int = 300,
    operation_timeout_s: int = 3600,
) -> asset_v1.ExportAssetsResponse:
    """
    Triggers an export and waits for completion.

    parent:
      "projects/<PROJECT_ID>"
      "folders/<FOLDER_ID>"
      "organizations/<ORG_ID>"

    gcs_uri:
      - recommended: prefix ending with "/" so we generate a unique filename:
          gs://my-bucket/asset-exports/
      - or a full object path:
          gs://my-bucket/asset-exports/export.ndjson

    asset_types:
      - None or empty -> export all supported asset types
      - e.g. ["storage.googleapis.com/Bucket"]
    """

    client = build_client(use_rest=use_rest, api_endpoint=api_endpoint)

    final_gcs_uri = normalise_gcs_uri(gcs_uri, parent)
    LOG.info("Export destination: %s", final_gcs_uri)

    output_config = asset_v1.OutputConfig(
        gcs_destination=asset_v1.GcsDestination(uri=final_gcs_uri)
    )

    request = asset_v1.ExportAssetsRequest(
        parent=parent,
        content_type=content_type,
        output_config=output_config,
        asset_types=list(asset_types) if asset_types else [],
    )

    # Retries for transient API errors when starting the LRO
    start_retry = retry.Retry(
        predicate=retry.if_exception_type(
            exceptions.DeadlineExceeded,
            exceptions.TooManyRequests,
            exceptions.InternalServerError,
            exceptions.BadGateway,
            exceptions.ServiceUnavailable,
        ),
        initial=1.0,
        maximum=60.0,
        multiplier=2.0,
        deadline=600.0,
    )

    try:
        LOG.info("Starting export operation for scope: %s", parent)
        op = client.export_assets(
            request=request,
            retry=start_retry,
            timeout=per_request_timeout_s,
        )

        LOG.info("Operation started. Waiting for completion (timeout=%ss)...", operation_timeout_s)
        resp = op.result(timeout=operation_timeout_s)

        LOG.info("Export completed successfully.")
        return resp

    except exceptions.PermissionDenied as e:
        LOG.error(
            "Permission denied.\n"
            "- Ensure your ADC identity can call Cloud Asset export on %s.\n"
            "- Ensure the Cloud Asset service agent can write to the bucket:\n"
            "  service-PROJECT_NUMBER@gcp-sa-cloudasset.iam.gserviceaccount.com\n"
            "  needs roles/storage.objectCreator on the destination bucket.\n"
            "Error: %s",
            parent,
            e,
        )
        raise

    except exceptions.GoogleAPICallError as e:
        LOG.error("Google API call failed: %s", e)
        raise


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export GCP Asset Inventory to GCS (NDJSON).")
    p.add_argument("--parent", required=True, help='Scope: "projects/ID" or "organizations/ORG_ID" or "folders/FOLDER_ID"')
    p.add_argument("--gcs-uri", required=True, help='Destination: "gs://bucket/path/" (prefix) or "gs://bucket/path/file.ndjson"')
    p.add_argument(
        "--asset-type",
        action="append",
        dest="asset_types",
        default=None,
        help='Repeatable. Example: --asset-type storage.googleapis.com/Bucket. If omitted, exports all asset types.',
    )
    p.add_argument(
        "--content-type",
        default="RESOURCE",
        choices=["RESOURCE", "IAM_POLICY", "ORG_POLICY", "ACCESS_POLICY"],
        help="Export content type.",
    )
    p.add_argument("--use-rest", action="store_true", default=True, help="Use REST transport (recommended on corp networks).")
    p.add_argument(
        "--api-endpoint",
        default=None,
        help='Optional. For VPC Service Controls: "restricted.googleapis.com" (or "private.googleapis.com").',
    )
    p.add_argument("--operation-timeout-s", type=int, default=3600, help="How long to wait for the export to finish.")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    content_type = getattr(asset_v1.ContentType, args.content_type)

    try:
        resp = export_assets_to_gcs(
            parent=args.parent,
            gcs_uri=args.gcs_uri,
            asset_types=args.asset_types,
            content_type=content_type,
            use_rest=args.use_rest,
            api_endpoint=args.api_endpoint,
            operation_timeout_s=args.operation_timeout_s,
        )
        # Response includes details of the output config and timing info
        LOG.info("Response: %s", resp)
        return 0
    except Exception:
        LOG.exception("Export failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())