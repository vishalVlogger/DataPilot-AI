# Commercial admin playbook

Open **System Admin → Business → Commercial** to inspect effective plan distribution, active and expiring trials, upgrade leads, manual assignments, over-limit workspaces, external-AI usage by plan, and the non-financial commercial funnel.

For an upgrade lead:

1. Mark it **Contacted** after outreach.
2. Use **Activate Pro/Business** only after an authorized commercial decision.
3. The action updates the workspace's unique manual subscription and marks the request approved. Both actions are in the System Admin audit log.
4. To revoke an assignment, call `POST /api/admin/commercial/workspaces/{workspace_id}/manual-plan` with `{"plan_code":"none","confirmed":true}`. Existing data remains intact.

Use `GET /api/admin/commercial/trials` for trial review and `GET /api/admin/commercial/upgrade-requests?status=pending` for lead queues. `GET /api/admin/commercial/summary` answers how many workspaces use each effective plan, which are in trial, which are over limits, and which requested upgrades.

Manual assignment means access was granted; it does not mean payment was collected. Revenue and profit must remain unavailable until real transaction and cost data exist.
