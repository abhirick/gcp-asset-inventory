
# GCP Asset Inventory Exporter — Quick Start & Usage Guide

![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![GCP](https://img.shields.io/badge/google--cloud-asset--inventory-4285F4)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-production--ready-brightgreen)

Export Google Cloud assets from a **single GCP project** using **Cloud Asset Inventory** and **Application Default Credentials (ADC)** into **JSON, CSV, or interactive HTML reports**.

---

## Features

* Secure authentication via ADC (no service account keys)
* Project-level Cloud Asset Inventory export
* Asset type filtering
* JSON / CSV export
* Interactive HTML report
* Asset normalization for reporting
* Streaming-safe for large inventories
* Clean modular architecture

---

## Requirements

* Python 3.9+
* gcloud CLI installed
* Cloud Asset API enabled
* IAM role: `roles/cloudasset.viewer`

---

## Installation

```bash
git clone https://github.com/<your-user>/gcp-asset-inventory-exporter.git
cd gcp-asset-inventory-exporter
pip install -r requirements.txt
```

---

## Authentication (ADC)

```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable cloudasset.googleapis.com
```

This creates local credentials automatically used by the exporter.

---

## Usage

### Required environment variable

```bash
export GCP_PROJECT_ID="your-project-id"
```

---

### JSON Export (default)

```bash
python gcp_asset_inventory_export.py
```

Output:

```
gcp_assets.json
```

---

### CSV Export

```bash
export EXPORT_FORMAT="csv"
export EXPORT_PATH="assets.csv"
python gcp_asset_inventory_export.py
```

---

### HTML Export (Interactive Report)

```bash
export EXPORT_FORMAT="html"
export EXPORT_PATH="gcp_assets.html"
python gcp_asset_inventory_export.py
```

Open report:

**macOS:**

```bash
open gcp_assets.html
```

**Linux:**

```bash
xdg-open gcp_assets.html
```

---

## Filter Specific Asset Types

Example: Compute instances + Storage buckets:

```bash
export GCP_ASSET_TYPES="compute.googleapis.com/Instance,storage.googleapis.com/Bucket"
export EXPORT_FORMAT="html"
python gcp_asset_inventory_export.py
```

---

## How the exporter works (flow)

```
Cloud Asset Inventory API
        ↓
AssetServiceClient (ADC)
        ↓
ListAssets (paged)
        ↓
Normalize fields
        ↓
Exporter (JSON / CSV / HTML)
```

---

##  HTML Report Capabilities

*  Searchable
*  Sortable columns
*  Asset count summary
*  Clean UI
*  Responsive layout
*  Offline-compatible

---

## Required IAM Permission

The authenticated identity must have:

```
roles/cloudasset.viewer
```

Project-level permission is sufficient.

---

## Environment Variables

| Variable        | Required | Description                 |
| --------------- | -------- | --------------------------- |
| GCP_PROJECT_ID  | ✅        | Target GCP project          |
| GCP_ASSET_TYPES | ❌        | Comma-separated asset types |
| EXPORT_FORMAT   | ❌        | json / csv / html           |
| EXPORT_PATH     | ❌        | Output file path            |

Defaults:

```
EXPORT_FORMAT=json
EXPORT_PATH=gcp_assets.json
```

---

## Example Full Run

```bash
export GCP_PROJECT_ID="my-project"
export GCP_ASSET_TYPES="compute.googleapis.com/Instance,storage.googleapis.com/Bucket"
export EXPORT_FORMAT="html"
export EXPORT_PATH="inventory.html"

python gcp_asset_inventory_export.py
open inventory.html
```

---

## Architecture

```
Cloud Asset API
        ↓
AssetServiceClient (ADC)
        ↓
ListAssets (paged)
        ↓
Normalize fields
        ↓
Exporter (JSON / CSV / HTML)
```

---
