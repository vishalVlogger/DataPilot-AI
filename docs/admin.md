# System Admin Console

`/admin` is the DataPilot platform-operations console. It uses a dedicated layout and never displays normal upload, Ask Data, Charts, Clean, Reports, or Export navigation. A system administrator who needs the ordinary product can select **Open User App**.

## Roles and privacy

- **Workspace Admin** manages membership and policy inside one workspace. This role cannot access `/admin` or `/api/admin/*`.
- **System Admin** monitors and safely operates the DataPilot platform. Every admin API enforces `is_system_admin` on the backend.

The console covers overview, users, workspaces, usage, health, jobs, grouped errors, storage, providers, feedback, support, audit, and business metrics. Lists use backend pagination and filters. Dataset visibility is limited to identifiers, names, dimensions, row/column counts, size, versions, and timestamps. Dataset contents and internal storage keys are not exposed.

Platform status is **Critical** when required database or storage is unavailable, **Degraded** when a configured optional provider is unavailable, and **Healthy** when required dependencies pass and no configured provider is known to be failing.

Business reporting shows only real beta users, plan distribution, external-AI calls, and storage consumption. Billing is not implemented, so revenue, MRR, ARR, profit, and estimated cost are unavailable rather than reported as zero.

## Bootstrap and removal

Run from the backend directory on a trusted application host:

```powershell
python -m app.cli make-system-admin admin@example.com
python -m app.cli remove-system-admin admin@example.com
```

The account must already exist. These commands do not change passwords. They write a safe audit record, and removal refuses to revoke the last active system administrator. Console actions require explicit confirmation, prevent self-lockout, and are audited with the actor, action, target, request ID, and safe metadata.

System errors store only safe grouping metadata: request ID, error code, route, method, status, optional user/workspace identifiers, safe message, occurrence count, and first/last seen timestamps. Passwords, tokens, API keys, request bodies, dataset rows, internal paths, and stack traces are excluded.
