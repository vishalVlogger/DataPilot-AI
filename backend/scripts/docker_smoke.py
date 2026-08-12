"""Disposable end-to-end smoke test for the local Docker staging stack."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import httpx


def checked(response: httpx.Response, expected: int | tuple[int, ...] = 200):
    statuses = (expected,) if isinstance(expected, int) else expected
    if response.status_code not in statuses:
        raise RuntimeError(f"{response.request.method} {response.request.url.path}: {response.status_code} {response.text[:500]}")
    if response.status_code == 204: return None
    content_type = response.headers.get("content-type", "")
    return response.json() if "json" in content_type else response.content


def wait_job(client: httpx.Client, headers: dict[str, str], job_id: str, timeout: int = 90) -> dict:
    deadline = time.monotonic() + timeout
    states: list[str] = []
    while time.monotonic() < deadline:
        job = checked(client.get(f"/api/jobs/{job_id}", headers=headers))
        if not states or states[-1] != job["status"]: states.append(job["status"])
        if job["status"] == "completed": return {**job, "observed_states": states}
        if job["status"] == "failed": raise RuntimeError(f"Job {job_id} failed: {job.get('error_message')}")
        time.sleep(0.5)
    raise RuntimeError(f"Job {job_id} timed out in states {states}")


def run(base_url: str) -> dict:
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    email = f"docker-smoke-{suffix}@example.com"; password = "DockerSmoke12345"
    with httpx.Client(base_url=base_url, timeout=60, follow_redirects=True, trust_env=False) as client:
        registration = checked(client.post("/api/auth/register", json={"email": email, "password": password, "display_name": "Docker Smoke", "beta_acknowledged": True}), 201)
        token = registration["access_token"]; workspace = registration["workspaces"][0]
        headers = {"Authorization": f"Bearer {token}", "X-Workspace-ID": workspace["id"]}
        verification_url = registration.get("development_verification_url")
        if not verification_url: raise RuntimeError("Console verification link is not enabled for local staging")
        verification_token = parse_qs(urlparse(verification_url).query)["token"][0]
        checked(client.post("/api/auth/verify-email", json={"token": verification_token}))
        checked(client.post("/api/auth/refresh"))
        login = checked(client.post("/api/auth/login", json={"email": email, "password": password}))
        headers["Authorization"] = f"Bearer {login['access_token']}"

        csv = b"car_name,price,mileage,region\nAlpha One,20000,10000,North\nBeta Two,18000,22000,West\nAlpha One,21000,9000,North\nGamma Three,15000,35000,East\nDelta Four,24000,8000,South\nEpsilon Five,17000,27000,West\n"
        dataset = checked(client.post("/api/datasets/upload", headers=headers, files={"file": ("car-details.csv", csv, "text/csv")}), 201)
        dataset_id = dataset["id"]
        profile = checked(client.get(f"/api/datasets/{dataset_id}/profile", headers=headers))
        ask = checked(client.post(f"/api/datasets/{dataset_id}/ask", headers=headers, json={"question": "Show top 5 car names"}))
        chart = checked(client.post(f"/api/datasets/{dataset_id}/chart", headers=headers, json={"question": "Show top 5 car names"}))
        cleaning = {"operations": [{"type": "trim_whitespace", "column": "car_name"}]}
        checked(client.post(f"/api/datasets/{dataset_id}/clean/preview", headers=headers, json=cleaning))
        applied = checked(client.post(f"/api/datasets/{dataset_id}/clean/apply", headers=headers, json={**cleaning, "confirmed": True}))
        versions = checked(client.get(f"/api/datasets/{dataset_id}/versions", headers=headers))
        checked(client.post(f"/api/datasets/{dataset_id}/versions/0/restore", headers=headers))
        exported = checked(client.get(f"/api/datasets/{dataset_id}/export?format=csv&version=current", headers=headers))

        report_request = checked(client.post(f"/api/datasets/{dataset_id}/report", headers=headers, json={"title": "Docker staging report", "format": "pdf", "async_job": True}), 202)
        report = wait_job(client, headers, report_request["job_id"])
        report_bytes = checked(client.get(f"/api/jobs/{report['id']}/result", headers=headers))

        feedback = checked(client.post("/api/feedback", headers=headers, json={"category": "general", "message": "Docker staging attachment smoke test", "current_page": "/", "dataset_id": dataset_id}), 201)
        png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415408d763f8ffff3f0005fe02fea73581980000000049454e44ae426082")
        attachment = checked(client.post(f"/api/feedback/{feedback['id']}/attachments", headers=headers, files={"files": ("smoke.png", png, "image/png")}), 201)
        invitation = checked(client.post(f"/api/workspaces/{workspace['id']}/invitations", headers=headers, json={"email": f"invite-{suffix}@example.com", "role": "member"}), 201)

        workspace_export_request = checked(client.post(f"/api/workspaces/{workspace['id']}/export", headers=headers, json={"include_raw_datasets": False}), 202)
        workspace_export = wait_job(client, headers, workspace_export_request["job_id"])
        workspace_zip = checked(client.get(f"/api/jobs/{workspace_export['id']}/result", headers=headers))

        disposable = checked(client.post("/api/workspaces", headers=headers, json={"name": f"Disposable {suffix}"}), 201)
        disposable_headers = {**headers, "X-Workspace-ID": disposable["id"]}
        deletion = checked(client.post(f"/api/workspaces/{disposable['id']}/deletion-request", headers=disposable_headers, json={"confirmation": disposable["name"]}), 202)
        read_only = client.patch(f"/api/workspaces/{disposable['id']}", headers=disposable_headers, json={"name": "Blocked"})
        if read_only.status_code != 409: raise RuntimeError(f"Deletion read-only guard returned {read_only.status_code}")
        checked(client.delete(f"/api/workspaces/{disposable['id']}/deletion-request", headers=disposable_headers))
        checked(client.post("/api/auth/logout"), 204)

    return {
        "status": "pass", "account": email, "workspace_id": workspace["id"], "dataset_id": dataset_id,
        "database_flow": "registered/verified/refreshed/logged-in/logged-out",
        "dataset": {"rows": dataset["rows"], "columns": dataset["columns"], "profile_columns": len(profile["columns"]), "version_created": applied["version"], "version_count": len(versions["versions"]), "csv_export_bytes": len(exported)},
        "chart": {"type": chart["type"], "rows": len(chart["data"]), "interpreted_request": chart["interpreted_request"], "tooltip_label": chart.get("tooltip_label")},
        "ask_interpreted_as": ask.get("metadata", {}).get("interpreted_as"),
        "report": {"bytes": len(report_bytes), "states": report["observed_states"]},
        "workspace_export": {"bytes": len(workspace_zip), "states": workspace_export["observed_states"]},
        "feedback_attachment": {"count": len(attachment), "bytes": attachment[0]["size"]},
        "invitation": {"status": invitation["status"], "console_link": bool(invitation.get("development_invitation_url"))},
        "deletion": {"scheduled_for": deletion["deletion_scheduled_for"], "read_only_status": read_only.status_code, "cancelled": True},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--base", default="http://backend:8000")
    print(json.dumps(run(parser.parse_args().base), indent=2))
