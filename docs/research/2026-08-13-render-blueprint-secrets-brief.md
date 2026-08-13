# Render Blueprint Secrets — Research Brief (2026-08-13)

## What we asked

What is the current (2026) correct syntax and best practice in `render.yaml` blueprints for
env vars whose values are secrets an operator fills in by hand in the Render dashboard?
Specifically: `sync: false` semantics on first deploy vs. subsequent syncs; whether env
groups / `fromGroup` / secret files are a newer preferred mechanism; overwrite gotchas
between blueprint-managed and dashboard-managed vars; and documentation conventions.
Checked against Render's official docs (blueprint YAML reference, Blueprints IaC guide,
env vars & secrets guide) as of August 2026.

## Findings

1. **`sync: false` is still the official mechanism for dashboard-managed secrets.** Syntax
   is unchanged — a `value` alongside it is optional and conventionally omitted:

   ```yaml
   envVars:
     - key: SECRET_KEY
       sync: false
   ```

   Semantics per the Blueprint YAML reference: during the **initial Blueprint creation
   flow** in the dashboard, Render prompts the operator to provide a value for each
   `sync: false` var. On **updates to an existing Blueprint, Render *ignores* any env vars
   with `sync: false`** — it neither prompts for them nor touches their dashboard values.

2. **Corollary gotcha — adding a new `sync: false` var to an already-synced blueprint does
   not prompt anyone.** Because syncs ignore `sync: false` entries, a newly added one is
   effectively documentation: the operator must create the var manually in the service's
   Environment tab. The blueprint line still earns its keep (inventory, preview-env
   awareness, prompting on any *fresh* blueprint deploy), but the runbook must carry the
   "set it in the dashboard" step.

3. **Sync overwrite rules** (Blueprints IaC guide):
   - Dashboard changes that **conflict with configuration defined in the Blueprint are
     overwritten on the next sync** — so never hand-edit in the dashboard a var that has a
     literal `value:` in `render.yaml`.
   - Vars **omitted from the blueprint are preserved**: "the resource retains any existing
     environment variable values that aren't overwritten by the Blueprint," and syncing
     never deletes an existing resource.
   - `sync: false` vars sit safely in the middle: declared in the file, values owned by
     the dashboard, immune to sync overwrite.

4. **Env groups and `fromGroup` are a complement, not a replacement.** Root-level
   `envVarGroups` define shared plain-value config; a service links one with a
   `fromGroup` entry in its `envVars` list:

   ```yaml
   envVarGroups:
     - name: shared-config
       envVars:
         - key: LOG_LEVEL
           value: info
   services:
     - type: web
       envVars:
         - fromGroup: shared-config
   ```

   But **`sync: false` is not allowed inside an env group** (Render ignores it there), so
   groups cannot hold hand-entered secrets from a blueprint. Service-level vars override
   linked-group values. `generateValue: true` remains available for secrets Render can
   mint itself (random 256-bit base64) — right for keys nothing external must match, wrong
   for shared secrets a peer system also holds.

5. **Secret files are a dashboard/env-group feature, not a blueprint one.** Uploaded via
   the dashboard, mounted at `/etc/secrets/<filename>` (1 MB combined limit per
   service/group); the blueprint spec has no syntax for declaring them. Relevant only for
   multi-line material like PEM keys, and even Render's own generated blueprints don't use
   them — `LTI_PRIVATE_KEY` as a `sync: false` \n-escaped var remains a fine pattern.

6. **Documentation convention:** Render's dashboard-generated blueprints emit each var's
   *name* with `sync: false` and no value, precisely to keep secrets out of git. The
   prevailing OSS convention (Render's own examples, fief, CodiMD) is a `# comment` above
   each `sync: false` line saying what to set and how to generate it, plus a runbook/README
   step — exactly what Original's `render.yaml` already does (generation commands for
   `SECRET_KEY`, pointers to `docs/OPS_RUNBOOK.md` / `docs/CANVAS_RUNBOOK.md`).
   One more behavior to know: `sync: false` vars are **not copied into preview
   environments**.

## Recommendation for Original's render.yaml

The repo's existing pattern (`SECRET_KEY`, `MAINTENANCE_TOKEN`, `LTI_PRIVATE_KEY`,
`DATABASE_URL`, `REPO_*`, `AI_LIKELIHOOD_SHADOW` — all `sync: false` under
`original-pilot` with explanatory comments) is still the correct, current best practice.
Add the Bluebook pair the same way:

```yaml
      # ── Bluebook integration (dashboard-managed, inert until set) ──
      # BBOOK_API_URL         — Bluebook endpoint for this deployment.
      # BBOOK_EXTERNAL_SECRET — shared secret; must match the value configured
      #                         on the Bluebook side. Generate:
      #   python -c "import secrets; print(secrets.token_urlsafe(48))"
      - key: BBOOK_API_URL
        sync: false
      - key: BBOOK_EXTERNAL_SECRET
        sync: false
```

Both are no-ops while unset (matching the app's fail-inert defaults), and `sync: false`
keeps them dashboard-owned and sync-proof. Since the pilot blueprint is already deployed,
**syncing this change will not prompt for values** (finding 2) — add a provisioning-
checklist/runbook step to set both in the dashboard. If `BBOOK_API_URL` ever becomes a
stable non-secret URL, it could graduate to a literal `value:` — but then dashboard edits
to it would be overwritten on sync (finding 3), so keep it `sync: false` while the
endpoint is deployment-specific. Do not use `generateValue` for the shared secret (the
Bluebook side must hold the same value) and don't move either into an env group (groups
can't carry `sync: false`).

## Sources

- [Blueprint YAML Reference — Render Docs](https://render.com/docs/blueprint-spec) — `envVars` syntax, `sync: false` first-deploy prompt and "ignored on update" rule, `generateValue`, `envVarGroups`, `fromGroup`, `previewValue`.
- [Render Blueprints (IaC) — Render Docs](https://render.com/docs/infrastructure-as-code) — sync semantics: dashboard conflicts overwritten, omitted vars preserved, no deletion on sync, generated blueprints emit names with `sync: false`.
- [Environment Variables and Secrets — Render Docs](https://render.com/docs/configure-environment-variables) — secret files (`/etc/secrets/<filename>`, 1 MB limit), env groups, service-over-group precedence, "don't commit secret values to render.yaml."
- [Preview Environments — Render Docs](https://render.com/docs/preview-environments) — `sync: false` vars are not included in preview environments.
- [Render community: blueprint + web-admin env vars](https://community.render.com/t/if-i-declare-a-render-yaml-blueprint-can-i-specify-env-vars-through-the-web-admin/17190) — confirms dashboard-set vars outside the blueprint persist across syncs.
