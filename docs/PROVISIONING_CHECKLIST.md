# Pilot Provisioning Checklist (operator)

Manual steps to onboard one institution + its professors. ~30 minutes total.
All write calls need the guard header: `-H "X-Guard-Token: $MAINTENANCE_TOKEN"`
(the pilot runs `GUARD_DESTRUCTIVE=1`). Base URL below: `$HOST`.

## 1. Tenant

```bash
curl -s -X POST $HOST/tenants -H 'Content-Type: application/json' \
  -d '{"tenant_id":"<slug>","name":"<Institution Name>","environment":"pilot"}'
```
- [ ] Slug is lowercase-kebab, final (it prefixes every student id — never rename).
- [ ] `GET $HOST/tenants` shows it with `environment: pilot`.

## 2. Professor accounts (repeat ×5)

```bash
curl -s -X POST $HOST/auth/register \
  -H 'Content-Type: application/json' -H "X-Guard-Token: $MAINTENANCE_TOKEN" \
  -d '{"email":"<prof@inst.edu>","password":"<generated>","role":"professor",
       "tenant_id":"<slug>","name":"<Dr. Full Name>"}'
```
- [ ] Generate each password: `python -c "import secrets; print(secrets.token_urlsafe(12))"`.
- [ ] One `admin`-role account for the department chair / registrar contact (optional).
- [ ] Record who-got-what in the password manager.

**Credential delivery:** there is no email flow. Deliver each credential
directly (in the onboarding session, or via the institution's secure channel),
and have the professor log in while you watch — that's the verification step.

**Password reset (manual):** there is no self-serve reset. The operator
re-issues by calling `/auth/register`'s guarded upsert path with a new password
for the same email/tenant, then delivers it again. Log it in PILOT_LOG.md.

## 3. Per-professor verification (the watch-them-do-it list)

- [ ] Professor logs in at `$HOST/bluebook/` (or via Canvas course nav once LTI is live).
- [ ] Sidebar shows their name + `professor · <slug>` — not "Demo Session".
- [ ] Examinations/Courses/Students/Results are EMPTY (their tenant is fresh — if they see demo data, STOP: the auth bridge isn't attaching, or they're on the wrong host).
- [ ] They create one throwaway course and one draft exam, then delete confusion by walking the quickstart.

## 4. Isolation spot-check (once per institution)

- [ ] Logged in as a pilot professor, `GET $HOST/students` returns only `<slug>:*` ids (empty at first).
- [ ] Anonymous `GET $HOST/students/<slug>:anything` → 403.
- [ ] The public demo (`original-demo` service) shows none of this tenant's data.

## 5. Before real students

- [ ] DPA signed (docs/dpa_template.md) — date: ____
- [ ] Student disclosure text in each course syllabus (docs/STUDENT_DISCLOSURE.md).
- [ ] LTI verified per docs/CANVAS_RUNBOOK.md §3.
- [ ] Last-48h run of docs/PILOT_SMOKE_TEST.md is 100%.
