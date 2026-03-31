#!/usr/bin/env python3
"""
GCP Infrastructure Inventory Reporter
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pulls infrastructure data from a GCP project using:
  1. Cloud Asset Search API  – broad resource search (search_all_resources)
  2. Cloud Asset List API    – full resource metadata (list_assets)

Authentication: Application Default Credentials (ADC)
Output:         Fancy green-and-black HTML report, optional PDF

Dependencies:
    pip install google-cloud-asset google-auth jinja2
    pip install weasyprint   # only for --pdf

Usage:
    python gcp_inventory.py --project my-gcp-project-id
    python gcp_inventory.py --project my-gcp-project-id --pdf
    python gcp_inventory.py --project my-gcp-project-id --output report.html --pdf
"""

import argparse
import datetime
import getpass
import os
import platform
import socket
import sys
from collections import defaultdict

# ── Google Cloud ──────────────────────────────────────────────────────────────
try:
    from google.cloud import asset_v1
    from google.auth import default as google_auth_default
    from google.auth.exceptions import DefaultCredentialsError
except ImportError:
    sys.exit(
        "Missing google-cloud-asset / google-auth.\n"
        "Install: pip install google-cloud-asset google-auth"
    )

try:
    from jinja2 import Environment, BaseLoader
except ImportError:
    sys.exit("Missing jinja2. Install: pip install jinja2")


# ─────────────────────────────────────────────────────────────────────────────
# FRIENDLY TYPE LABELS
# ─────────────────────────────────────────────────────────────────────────────
FRIENDLY_TYPE: dict[str, str] = {
    # ── Compute ───────────────────────────────────────────────────────────────
    "compute.googleapis.com/Instance":                    "Compute Engine Instances",
    "compute.googleapis.com/Disk":                        "Persistent Disks",
    "compute.googleapis.com/Snapshot":                    "Disk Snapshots",
    "compute.googleapis.com/Image":                       "Custom Images",
    "compute.googleapis.com/MachineImage":                "Machine Images",
    "compute.googleapis.com/InstanceTemplate":            "Instance Templates",
    "compute.googleapis.com/InstanceGroup":               "Instance Groups",
    "compute.googleapis.com/InstanceGroupManager":        "Managed Instance Groups",
    "compute.googleapis.com/Autoscaler":                  "Autoscalers",

    # ── Networking ───────────────────────────────────────────────────────────
    "compute.googleapis.com/Network":                     "VPC Networks",
    "compute.googleapis.com/Subnetwork":                  "Subnetworks",
    "compute.googleapis.com/Firewall":                    "Firewall Rules",
    "compute.googleapis.com/FirewallPolicy":              "Firewall Policies",
    "compute.googleapis.com/Address":                     "External IP Addresses",
    "compute.googleapis.com/GlobalAddress":               "Global IP Addresses",
    "compute.googleapis.com/Route":                       "Routes",
    "compute.googleapis.com/Router":                      "Cloud Routers",
    "compute.googleapis.com/VpnGateway":                  "VPN Gateways",
    "compute.googleapis.com/VpnTunnel":                   "VPN Tunnels",
    "compute.googleapis.com/InterconnectAttachment":      "Interconnect Attachments",
    "compute.googleapis.com/Interconnect":                "Dedicated Interconnects",
    "compute.googleapis.com/NetworkEndpointGroup":        "Network Endpoint Groups",

    # ── Load Balancing ───────────────────────────────────────────────────────
    "compute.googleapis.com/BackendService":              "Backend Services",
    "compute.googleapis.com/BackendBucket":               "Backend Buckets",
    "compute.googleapis.com/UrlMap":                      "URL Maps / Load Balancers",
    "compute.googleapis.com/TargetHttpProxy":             "Target HTTP Proxies",
    "compute.googleapis.com/TargetHttpsProxy":            "Target HTTPS Proxies",
    "compute.googleapis.com/TargetSslProxy":              "Target SSL Proxies",
    "compute.googleapis.com/TargetTcpProxy":              "Target TCP Proxies",
    "compute.googleapis.com/ForwardingRule":              "Forwarding Rules",
    "compute.googleapis.com/GlobalForwardingRule":        "Global Forwarding Rules",
    "compute.googleapis.com/HealthCheck":                 "Health Checks",
    "compute.googleapis.com/SslCertificate":              "SSL Certificates",
    "compute.googleapis.com/SslPolicy":                   "SSL Policies",

    # ── GKE ──────────────────────────────────────────────────────────────────
    "container.googleapis.com/Cluster":                   "GKE Clusters",
    "container.googleapis.com/NodePool":                  "GKE Node Pools",

    # ── Serverless ───────────────────────────────────────────────────────────
    "cloudfunctions.googleapis.com/CloudFunction":        "Cloud Functions (Gen 1)",
    "cloudfunctions.googleapis.com/Function":             "Cloud Functions (Gen 2)",
    "run.googleapis.com/Service":                         "Cloud Run Services",
    "run.googleapis.com/Job":                             "Cloud Run Jobs",
    "appengine.googleapis.com/Application":               "App Engine Applications",
    "appengine.googleapis.com/Service":                   "App Engine Services",
    "appengine.googleapis.com/Version":                   "App Engine Versions",

    # ── Storage ──────────────────────────────────────────────────────────────
    "storage.googleapis.com/Bucket":                      "Cloud Storage Buckets",
    "filestore.googleapis.com/Instance":                  "Filestore Instances",
    "filestore.googleapis.com/Backup":                    "Filestore Backups",

    # ── Databases ────────────────────────────────────────────────────────────
    "sqladmin.googleapis.com/Instance":                   "Cloud SQL Instances",
    "spanner.googleapis.com/Instance":                    "Cloud Spanner Instances",
    "spanner.googleapis.com/Database":                    "Cloud Spanner Databases",
    "bigtable.googleapis.com/Instance":                   "Cloud Bigtable Instances",
    "bigtable.googleapis.com/Cluster":                    "Bigtable Clusters",
    "redis.googleapis.com/Instance":                      "Memorystore (Redis)",
    "memcache.googleapis.com/Instance":                   "Memorystore (Memcached)",
    "alloydb.googleapis.com/Cluster":                     "AlloyDB Clusters",
    "alloydb.googleapis.com/Instance":                    "AlloyDB Instances",
    "firestore.googleapis.com/Database":                  "Firestore Databases",
    "datastore.googleapis.com/Index":                     "Datastore Indexes",

    # ── BigQuery ─────────────────────────────────────────────────────────────
    "bigquery.googleapis.com/Dataset":                    "BigQuery Datasets",
    "bigquery.googleapis.com/Table":                      "BigQuery Tables",
    "bigquery.googleapis.com/Routine":                    "BigQuery Routines",
    "bigquerydatatransfer.googleapis.com/TransferConfig": "BigQuery Transfer Configs",
    "bigqueryreservation.googleapis.com/Reservation":     "BigQuery Reservations",

    # ── Messaging / Streaming ────────────────────────────────────────────────
    "pubsub.googleapis.com/Topic":                        "Pub/Sub Topics",
    "pubsub.googleapis.com/Subscription":                 "Pub/Sub Subscriptions",
    "pubsub.googleapis.com/Snapshot":                     "Pub/Sub Snapshots",
    "pubsublite.googleapis.com/Topic":                    "Pub/Sub Lite Topics",
    "pubsublite.googleapis.com/Subscription":             "Pub/Sub Lite Subscriptions",

    # ── Data & Analytics ─────────────────────────────────────────────────────
    "dataflow.googleapis.com/Job":                        "Dataflow Jobs",
    "dataproc.googleapis.com/Cluster":                    "Dataproc Clusters",
    "dataproc.googleapis.com/AutoscalingPolicy":          "Dataproc Autoscaling Policies",
    "composer.googleapis.com/Environment":                "Cloud Composer Environments",
    "datafusion.googleapis.com/Instance":                 "Cloud Data Fusion Instances",
    "dataplex.googleapis.com/Lake":                       "Dataplex Lakes",
    "dataplex.googleapis.com/Zone":                       "Dataplex Zones",
    "datastream.googleapis.com/Stream":                   "Datastream Streams",
    "dataform.googleapis.com/Repository":                 "Dataform Repositories",

    # ── AI / ML ──────────────────────────────────────────────────────────────
    "aiplatform.googleapis.com/Dataset":                  "Vertex AI Datasets",
    "aiplatform.googleapis.com/Endpoint":                 "Vertex AI Endpoints",
    "aiplatform.googleapis.com/Model":                    "Vertex AI Models",
    "aiplatform.googleapis.com/Featurestore":             "Vertex AI Featurestores",
    "aiplatform.googleapis.com/IndexEndpoint":            "Vertex AI Index Endpoints",
    "notebooks.googleapis.com/Instance":                  "Notebooks (Legacy)",
    "ml.googleapis.com/Model":                            "AI Platform Models (Legacy)",

    # ── DevOps & CI/CD ───────────────────────────────────────────────────────
    "artifactregistry.googleapis.com/Repository":         "Artifact Registry Repos",
    "cloudbuild.googleapis.com/BuildTrigger":             "Cloud Build Triggers",
    "cloudbuild.googleapis.com/WorkerPool":               "Cloud Build Worker Pools",
    "binaryauthorization.googleapis.com/Policy":          "Binary Authorization Policies",
    "sourcerepo.googleapis.com/Repo":                     "Cloud Source Repositories",

    # ── IAM & Security ───────────────────────────────────────────────────────
    "iam.googleapis.com/ServiceAccount":                  "Service Accounts",
    "iam.googleapis.com/ServiceAccountKey":               "Service Account Keys",
    "iam.googleapis.com/Role":                            "Custom IAM Roles",
    "iam.googleapis.com/WorkloadIdentityPool":            "Workload Identity Pools",
    "cloudkms.googleapis.com/KeyRing":                    "KMS Key Rings",
    "cloudkms.googleapis.com/CryptoKey":                  "KMS Crypto Keys",
    "secretmanager.googleapis.com/Secret":                "Secret Manager Secrets",
    "certificatemanager.googleapis.com/Certificate":      "Certificate Manager Certs",
    "certificatemanager.googleapis.com/CertificateMap":   "Certificate Maps",
    "recaptchaenterprise.googleapis.com/Key":             "reCAPTCHA Enterprise Keys",

    # ── DNS & Networking Services ────────────────────────────────────────────
    "dns.googleapis.com/ManagedZone":                     "Cloud DNS Zones",
    "dns.googleapis.com/Policy":                          "Cloud DNS Policies",
    "networkservices.googleapis.com/Gateway":             "Network Gateways",

    # ── Observability ────────────────────────────────────────────────────────
    "logging.googleapis.com/LogSink":                     "Log Sinks (Exports)",
    "logging.googleapis.com/LogBucket":                   "Log Buckets",
    "logging.googleapis.com/LogMetric":                   "Log-based Metrics",
    "monitoring.googleapis.com/AlertPolicy":              "Alert Policies",
    "monitoring.googleapis.com/NotificationChannel":      "Notification Channels",
    "monitoring.googleapis.com/Dashboard":                "Monitoring Dashboards",
    "monitoring.googleapis.com/UptimeCheckConfig":        "Uptime Checks",

    # ── Service Management ───────────────────────────────────────────────────
    "servicemanagement.googleapis.com/ManagedService":    "Managed Services (APIs)",
    "endpoints.googleapis.com/Service":                   "Cloud Endpoints Services",
    "apigee.googleapis.com/Organization":                 "Apigee Organizations",
    "apigee.googleapis.com/Environment":                  "Apigee Environments",

    # ── Workflows & Scheduling ───────────────────────────────────────────────
    "workflows.googleapis.com/Workflow":                  "Workflows",
    "cloudscheduler.googleapis.com/Job":                  "Cloud Scheduler Jobs",
    "cloudtasks.googleapis.com/Queue":                    "Cloud Tasks Queues",

    # ── Access / Policy ──────────────────────────────────────────────────────
    "accessapproval.googleapis.com/AccessApprovalSettings": "Access Approval Settings",
    "orgpolicy.googleapis.com/Policy":                    "Org Policies",
    "accesscontextmanager.googleapis.com/AccessPolicy":   "Access Policies (VPC-SC)",
    "accesscontextmanager.googleapis.com/ServicePerimeter": "Service Perimeters (VPC-SC)",

    # ── Resource Management ──────────────────────────────────────────────────
    "cloudresourcemanager.googleapis.com/Project":        "GCP Projects",
    "cloudresourcemanager.googleapis.com/Folder":         "Resource Folders",
    "billingbudgets.googleapis.com/Budget":               "Billing Budgets",

     # ── Resource Management ──────────────────────────────────────────────────
    "serviceusage.googleapis.com/Service":                "Enabled Services"
}


def friendly(asset_type: str) -> str:
    return FRIENDLY_TYPE.get(asset_type, "Other Assets")


# ─────────────────────────────────────────────────────────────────────────────
# CREDENTIALS
# ─────────────────────────────────────────────────────────────────────────────

def get_credentials():
    try:
        creds, project = google_auth_default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        return creds, project
    except DefaultCredentialsError:
        sys.exit(
            "No Application Default Credentials found.\n"
            "Run: gcloud auth application-default login"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 1. SEARCH ALL RESOURCES
# ─────────────────────────────────────────────────────────────────────────────

def fetch_search_resources(client: asset_v1.AssetServiceClient, scope: str) -> list[dict]:
    print("[1/2] search_all_resources ...")
    assets = []
    request = asset_v1.SearchAllResourcesRequest(scope=scope, page_size=500)
    for r in client.search_all_resources(request=request):
        assets.append({
            "name":          (r.name or r.display_name or "-").split("/")[-1],
            "full_name":     r.name or "",
            "asset_type":    r.asset_type,
            "friendly_type": friendly(r.asset_type),
            "location":      r.location or "global",
            "state":         r.state or "ACTIVE",
            "labels":        dict(r.labels) if r.labels else {},
            "description":   r.description or "",
            "source":        "search",
        })
    print(f"    -> {len(assets)} resources found")
    return assets


# ─────────────────────────────────────────────────────────────────────────────
# 2. LIST ALL ASSETS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_list_assets(client: asset_v1.AssetServiceClient, project_id: str) -> list[dict]:
    print("[2/2] list_assets (RESOURCE content type) ...")
    parent = f"projects/{project_id}"
    assets = []
    request = asset_v1.ListAssetsRequest(
        parent=parent,
        content_type=asset_v1.ContentType.RESOURCE,
        page_size=500,
    )
    try:
        for a in client.list_assets(request=request):
            atype = a.asset_type
            name = a.name or ""
            location = "global"
            if a.resource and a.resource.data:
                data = dict(a.resource.data)
                location = (
                    data.get("location")
                    or data.get("region")
                    or data.get("zone")
                    or "global"
                )
            assets.append({
                "name":          name.split("/")[-1],
                "full_name":     name,
                "asset_type":    atype,
                "friendly_type": friendly(atype),
                "location":      location,
                "state":         "ACTIVE",
                "labels":        {},
                "description":   "",
                "source":        "list",
            })
        print(f"    -> {len(assets)} assets listed")
    except Exception as e:
        print(f"    [!] list_assets failed: {e}")
    return assets


# ─────────────────────────────────────────────────────────────────────────────
# DEDUP & GROUP
# ─────────────────────────────────────────────────────────────────────────────

def dedup_assets(search_assets: list[dict], list_assets_: list[dict]) -> list[dict]:
    """Merge: search results are richer; list catches types search misses."""
    seen: set[str] = set()
    merged: list[dict] = []

    for a in search_assets:
        key = a["full_name"] or a["name"]
        if key not in seen:
            seen.add(key)
            merged.append(a)

    for a in list_assets_:
        key = a["full_name"] or a["name"]
        if key not in seen:
            seen.add(key)
            merged.append(a)

    return merged


def group_assets(assets: list[dict]) -> dict:
    grouped: dict[str, list] = defaultdict(list)
    for a in assets:
        grouped[a["friendly_type"]].append(a)
    return dict(sorted(grouped.items()))


# ─────────────────────────────────────────────────────────────────────────────
# METADATA
# ─────────────────────────────────────────────────────────────────────────────

def build_metadata(project_id: str, assets: list[dict], credentials) -> dict:
    adc_account = (
        getattr(credentials, "service_account_email", None)
        or getattr(credentials, "_service_account_email", None)
        or "User / Impersonated ADC"
    )
    unique_types = sorted({a["asset_type"] for a in assets})
    unique_regions = sorted({a["location"] for a in assets if a["location"] != "global"})

    return {
        "project_id":     project_id,
        "generated_at":   datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "generated_by":   getpass.getuser(),
        "hostname":       socket.gethostname(),
        "os":             f"{platform.system()} {platform.release()}",
        "python_version": platform.python_version(),
        "auth_method":    "Application Default Credentials (ADC)",
        "adc_account":    adc_account,
        "tool":           "Cloud Asset Inventory API v1",
        "apis_used": [
            "searchAllResources",
            "listAssets (RESOURCE)",
        ],
        "total_assets":   len(assets),
        "unique_types":   len(unique_types),
        "unique_regions": len(unique_regions),
        "regions_active": unique_regions or ["global"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# HTML TEMPLATE
# ─────────────────────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>GCP Inventory - {{ meta.project_id }}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root{
    --bg: #f5f7fb;
    --bg-soft: #eef2f8;
    --card: rgba(255,255,255,0.82);
    --card-strong: rgba(255,255,255,0.94);
    --text: #0f172a;
    --muted: #64748b;
    --line: #e2e8f0;
    --primary: #2563eb;
    --primary-2: #7c3aed;
    --primary-soft: rgba(37,99,235,0.10);
    --success: #16a34a;
    --danger: #dc2626;
    --shadow: 0 12px 40px rgba(15,23,42,0.10);
    --shadow-soft: 0 6px 18px rgba(15,23,42,0.06);
  }

  *{box-sizing:border-box;margin:0;padding:0}
  html{scroll-behaviour:smooth}
  body{
    font-family:'Inter',system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    background:
      radial-gradient(circle at top left, rgba(124,58,237,0.10), transparent 28%),
      radial-gradient(circle at top right, rgba(37,99,235,0.12), transparent 26%),
      linear-gradient(180deg, #f8fafc 0%, #f3f6fb 100%);
    color:var(--text);
    min-height:100vh;
    line-height:1.55;
  }

  .shell{
    max-width: 1480px;
    margin: 0 auto;
    padding: 24px;
  }

  .topbar{
    position: sticky;
    top: 16px;
    z-index: 100;
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:16px;
    padding:16px 18px;
    margin-bottom: 22px;
    background: rgba(255,255,255,0.70);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border:1px solid rgba(255,255,255,0.7);
    border-radius: 22px;
    box-shadow: var(--shadow-soft);
  }

  .brand{
    display:flex;
    align-items:center;
    gap:14px;
    min-width: 0;
  }

  .logo{
    width:44px;
    height:44px;
    border-radius:14px;
    display:grid;
    place-items:center;
    color:#fff;
    font-weight:800;
    font-size:16px;
    letter-spacing:0.5px;
    background: linear-gradient(135deg, var(--primary), var(--primary-2));
    box-shadow: 0 10px 24px rgba(37,99,235,0.28);
    flex: 0 0 auto;
  }

  .brand-copy{
    min-width:0;
  }

  .brand-title{
    font-size:15px;
    font-weight:800;
    letter-spacing:-0.02em;
    color:var(--text);
  }

  .brand-sub{
    font-size:12px;
    color:var(--muted);
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
  }

  .timestamp{
    font-size:12px;
    color:var(--muted);
    background: var(--bg-soft);
    border:1px solid var(--line);
    border-radius:999px;
    padding:10px 14px;
    white-space:nowrap;
  }

  .hero{
    position: relative;
    overflow: hidden;
    padding: 34px;
    border-radius: 30px;
    background:
      radial-gradient(circle at 85% 15%, rgba(255,255,255,0.25), transparent 28%),
      linear-gradient(135deg, #1d4ed8 0%, #2563eb 38%, #4f46e5 100%);
    color: #fff;
    box-shadow: var(--shadow);
    margin-bottom: 26px;
  }

  .hero::after{
    content:"";
    position:absolute;
    right:-60px;
    top:-40px;
    width:240px;
    height:240px;
    border-radius:50%;
    background: rgba(255,255,255,0.10);
    filter: blur(4px);
  }

  .hero-label{
    display:inline-flex;
    align-items:center;
    gap:8px;
    padding:8px 12px;
    border-radius:999px;
    background: rgba(255,255,255,0.14);
    border:1px solid rgba(255,255,255,0.18);
    font-size:12px;
    font-weight:600;
    margin-bottom: 18px;
  }

  .hero-title{
    font-size: clamp(32px, 5vw, 52px);
    line-height:1.05;
    letter-spacing:-0.04em;
    font-weight: 800;
    margin-bottom: 10px;
    max-width: 900px;
  }

  .hero-sub{
    font-size:15px;
    color: rgba(255,255,255,0.86);
    max-width: 760px;
    margin-bottom: 26px;
  }

  .stats{
    display:grid;
    grid-template-columns: repeat(4, minmax(0,1fr));
    gap:16px;
  }

  .stat-pill{
    background: rgba(255,255,255,0.14);
    border:1px solid rgba(255,255,255,0.16);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border-radius: 22px;
    padding:18px 18px 16px;
  }

  .stat-pill .num{
    font-size:28px;
    line-height:1;
    font-weight:800;
    margin-bottom:8px;
    letter-spacing:-0.03em;
  }

  .stat-pill .lbl{
    font-size:12px;
    color: rgba(255,255,255,0.78);
    font-weight:600;
  }

  .page{
    display:block;
  }

  .main{
    display:block;
  }

  .content{
    min-width:0;
  }

  .accordion{
    margin-bottom: 22px;
    background: var(--card);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border:1px solid rgba(255,255,255,0.75);
    border-radius: 24px;
    box-shadow: var(--shadow-soft);
    overflow: hidden;
  }

  .accordion summary{
    list-style: none;
    cursor: pointer;
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:16px;
    padding:20px 22px;
    background: linear-gradient(180deg, rgba(255,255,255,0.72), rgba(255,255,255,0.55));
    border-bottom:1px solid transparent;
    user-select:none;
  }

  .accordion summary::-webkit-details-marker{
    display:none;
  }

  .accordion[open] summary{
    border-bottom-color: var(--line);
  }

  .accordion-left{
    display:flex;
    align-items:center;
    gap:12px;
    min-width:0;
  }

  .accordion-chevron{
    width:28px;
    height:28px;
    border-radius:999px;
    display:grid;
    place-items:center;
    background: var(--bg-soft);
    border:1px solid var(--line);
    color: var(--muted);
    font-size:13px;
    font-weight:700;
    flex:0 0 auto;
    transition: transform 0.18s ease;
  }

  .accordion[open] .accordion-chevron{
    transform: rotate(90deg);
  }

  .accordion-title{
    font-size:16px;
    font-weight:700;
    color:var(--text);
    letter-spacing:-0.02em;
    min-width:0;
    overflow:hidden;
    text-overflow:ellipsis;
    white-space:nowrap;
  }

  .accordion-count{
    font-size:12px;
    font-weight:700;
    color:var(--primary);
    background: var(--primary-soft);
    border:1px solid rgba(37,99,235,0.12);
    border-radius:999px;
    padding:8px 12px;
    white-space:nowrap;
  }

  .accordion-body{
    padding:0;
  }

  .table-wrap{
    width:100%;
    overflow-x:auto;
  }

  .asset-table{
    width:100%;
    border-collapse:separate;
    border-spacing:0;
    min-width: 980px;
  }

  .asset-table thead th{
    background: var(--card-strong);
    color:var(--muted);
    font-size:12px;
    font-weight:700;
    text-align:left;
    padding:16px 18px;
    border-bottom:1px solid var(--line);
  }

  .asset-table tbody tr{
    transition: background 0.18s ease;
  }

  .asset-table tbody tr:hover{
    background: rgba(37,99,235,0.04);
  }

  .asset-table td{
    padding:16px 18px;
    font-size:14px;
    border-bottom:1px solid #edf2f7;
    vertical-align:middle;
  }

  .asset-table tbody tr:last-child td{
    border-bottom:none;
  }

  .asset-table td.name-col{
    color:var(--text);
    font-weight:700;
    max-width:320px;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
  }

  .type-chip{
    display:inline-flex;
    align-items:center;
    padding:7px 10px;
    border-radius:999px;
    background:#f8fafc;
    border:1px solid var(--line);
    color:#334155;
    font-size:12px;
    font-weight:600;
  }

  .loc-col{
    color:var(--muted);
    white-space:nowrap;
  }

  .badge{
    display:inline-flex;
    align-items:center;
    gap:6px;
    border-radius:999px;
    padding:7px 10px;
    font-size:12px;
    font-weight:700;
    border:1px solid transparent;
  }

  .badge-active{
    background: rgba(22,163,74,0.10);
    color: var(--success);
    border-color: rgba(22,163,74,0.14);
  }

  .badge-inactive{
    background: rgba(220,38,38,0.10);
    color: var(--danger);
    border-color: rgba(220,38,38,0.14);
  }

  .badge-default{
    background: rgba(148,163,184,0.10);
    color: #475569;
    border-color: rgba(148,163,184,0.16);
  }

  .labels-cell{
    max-width: 360px;
  }

  .labels-wrap{
    display:flex;
    flex-wrap:wrap;
    gap:8px;
  }

  .label-pair{
    display:inline-flex;
    align-items:center;
    padding:6px 10px;
    border-radius:999px;
    background:#ffffff;
    border:1px solid var(--line);
    color:#475569;
    font-size:12px;
    font-weight:500;
  }

  .empty{
    padding:64px 24px;
    text-align:center;
    color:var(--muted);
    font-size:14px;
    background: var(--card);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border:1px solid rgba(255,255,255,0.75);
    border-radius: 24px;
    box-shadow: var(--shadow-soft);
  }

  footer{
    margin-top: 12px;
    padding: 24px 6px 10px;
    text-align:center;
    color:var(--muted);
    font-size:12px;
  }

  footer span{
    color:var(--text);
    font-weight:700;
  }

  @media (max-width: 1100px){
    .stats{
      grid-template-columns: repeat(2, minmax(0,1fr));
    }
  }

  @media (max-width: 760px){
    .shell{
      padding: 14px;
    }

    .topbar{
      top: 10px;
      padding: 14px;
      border-radius: 18px;
      flex-direction:column;
      align-items:flex-start;
    }

    .timestamp{
      white-space:normal;
    }

    .hero{
      padding: 24px;
      border-radius: 24px;
    }

    .stats{
      grid-template-columns: 1fr;
    }

    .accordion summary{
      padding:16px;
    }

    .asset-table th,
    .asset-table td{
      padding:14px;
    }
  }

  @media print{
    body{
      background:#fff;
    }
    .topbar{
      position:static;
      box-shadow:none;
      background:#fff;
      border:1px solid #ddd;
    }
    .hero{
      box-shadow:none;
    }
    .accordion{
      box-shadow:none;
      background:#fff;
      border:1px solid #ddd;
      break-inside: avoid;
    }
    .accordion summary{
      background:#fff;
    }
    .accordion[open] summary{
      border-bottom-color:#ddd;
    }
    @page{
      margin:16mm;
      size:A4;
    }
  }
</style>
</head>
<body>
<div class="shell">

  <div class="topbar">
    <div class="brand">
      <div class="logo">☁</div>
      <div class="brand-copy">
        <div class="brand-title">GCP Inventory Report</div>
        <div class="brand-sub">Cloud asset overview for {{ meta.project_id }}</div>
      </div>
    </div>
    <div class="timestamp">{{ meta.generated_at }}</div>
  </div>

  <div class="hero">
    <div class="hero-label">Infrastructure Overview</div>
    <div class="hero-title">{{ meta.project_id }}</div>
    <div class="hero-sub">A clean, modern inventory dashboard for reviewing project resources, asset types and deployment footprint.</div>
    <div class="stats">
      <div class="stat-pill">
        <div class="num">{{ meta.total_assets }}</div>
        <div class="lbl">Resources</div>
      </div>
      <div class="stat-pill">
        <div class="num">{{ meta.unique_types }}</div>
        <div class="lbl">Asset Types</div>
      </div>
      <div class="stat-pill">
        <div class="num">{{ grouped | length }}</div>
        <div class="lbl">Categories</div>
      </div>
      <div class="stat-pill">
        <div class="num">{{ meta.unique_regions }}</div>
        <div class="lbl">Regions</div>
      </div>
    </div>
  </div>

  <div class="page">
    <div class="main">
      <main class="content">
        {% for category, assets in grouped.items() %}
        <details class="accordion" {% if category == "Other Assets" %}open{% endif %}>
          <summary>
            <div class="accordion-left">
              <span class="accordion-chevron">›</span>
              <span class="accordion-title">{{ category }}</span>
            </div>
            <span class="accordion-count">{{ assets | length }} items</span>
          </summary>

          <div class="accordion-body">
            <div class="table-wrap">
              <table class="asset-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Asset Type</th>
                    <th>Location</th>
                    <th>State</th>
                    <th>Labels</th>
                  </tr>
                </thead>
                <tbody>
                  {% for a in assets %}
                  <tr>
                    <td class="name-col" title="{{ a.full_name }}">{{ a.name }}</td>
                    <td><span class="type-chip">{{ a.asset_type }}</span></td>
                    <td class="loc-col">{{ a.location }}</td>
                    <td>
                      {% set s = a.state | upper %}
                      {% if s == "ACTIVE" %}
                        <span class="badge badge-active">{{ s }}</span>
                      {% elif s in ["DELETED","INACTIVE"] %}
                        <span class="badge badge-inactive">{{ s }}</span>
                      {% else %}
                        <span class="badge badge-default">{{ s if s else "-" }}</span>
                      {% endif %}
                    </td>
                    <td class="labels-cell">
                      {% if a.labels %}
                        <div class="labels-wrap">
                          {% for k, v in a.labels.items() %}
                            <span class="label-pair">{{ k }}={{ v }}</span>
                          {% endfor %}
                        </div>
                      {% else %}
                        <span style="color:var(--muted)">-</span>
                      {% endif %}
                    </td>
                  </tr>
                  {% endfor %}
                </tbody>
              </table>
            </div>
          </div>
        </details>
        {% else %}
        <div class="empty">No assets found. Verify project ID and Cloud Asset API permissions.</div>
        {% endfor %}
      </main>
    </div>
  </div>

  <footer>
    <span>gcp_inventory.py</span> · Generated for <span>{{ meta.project_id }}</span> · {{ meta.generated_at }}
  </footer>

</div>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────────────
# RENDER
# ─────────────────────────────────────────────────────────────────────────────

def render_html(meta: dict, grouped: dict) -> str:
    env = Environment(loader=BaseLoader())
    tmpl = env.from_string(HTML_TEMPLATE)
    return tmpl.render(meta=meta, grouped=grouped)


def render_pdf(html: str, pdf_path: str):
    try:
        from weasyprint import HTML as WP
    except ImportError:
        print("[!] weasyprint not installed. PDF skipped.\n    pip install weasyprint")
        return

    print(f"[*] Rendering PDF -> {pdf_path}")
    WP(string=html).write_pdf(pdf_path)
    print(f"[✓] PDF saved: {pdf_path}")


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="GCP Infrastructure Inventory Reporter")
    parser.add_argument("--project", required=True, help="GCP project ID")
    parser.add_argument("--output", default="gcp_inventory.html", help="Output HTML path")
    parser.add_argument("--pdf", action="store_true", help="Also export PDF (needs weasyprint)")
    args = parser.parse_args()

    credentials, _ = get_credentials()
    client = asset_v1.AssetServiceClient(credentials=credentials)
    scope = f"projects/{args.project}"

    search_results = fetch_search_resources(client, scope)
    list_results = fetch_list_assets(client, args.project)
    assets = dedup_assets(search_results, list_results)

    grouped = group_assets(assets)
    meta = build_metadata(args.project, assets, credentials)

    print("\n[*] Summary:")
    print(
        f"    Resources : {meta['total_assets']}  "
        f"({meta['unique_types']} types, {meta['unique_regions']} regions)"
    )

    html = render_html(meta, grouped)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[✓] HTML report -> {args.output}")

    if args.pdf:
        render_pdf(html, os.path.splitext(args.output)[0] + ".pdf")


if __name__ == "__main__":
    main()