/**
 * fixtures/api-setup.mjs — API-driven test data provisioning (WS-9 Stage 0.1).
 *
 * Creates tenant/staff/student/course/exam via the same REST endpoints
 * `original/api.py` exposes, so a spec no longer has to lean on the shared
 * demo seed. This is what makes per-worker tenancy isolation (Stage 0.2,
 * see fixtures/tenancy.mjs) possible: each worker calls these to build its
 * own tenant instead of racing other workers over one global seed.
 *
 * Auth model (see original/principal.py): staff/operator identities carry a
 * signed principal token minted by POST /auth/login and sent back as
 * `Authorization: Bearer <token>`; students carry a session token from
 * POST /student-auth/login. Neither is a cookie — see
 * docs/phase3-httpOnly-cookie-auth.md's own banner disclaiming itself as
 * the live auth path.
 */

let _uniqueCounter = 0
function unique(prefix) {
  _uniqueCounter += 1
  return `${prefix}-${process.pid}-${Date.now()}-${_uniqueCounter}`
}

async function okJson(res, label) {
  if (!res.ok()) {
    throw new Error(`${label} failed: ${res.status()} ${await res.text()}`)
  }
  return res.json()
}

export async function createTenant(request, { tenantId, name, environment = 'pilot', authToken } = {}) {
  const id = tenantId || unique('e2e-tenant')
  // /tenants is staff-only-gated once ORIGINAL_ENV=pilot (tenant_isolation
  // middleware, original/api.py _STAFF_ONLY_EXACT) — which is exactly the env
  // CI boots the server with. An authenticated (non-demo) principal token is
  // required there; anonymous only works locally against ORIGINAL_ENV=demo.
  const headers = authToken ? { Authorization: `Bearer ${authToken}` } : undefined
  const res = await request.post('/tenants', {
    headers,
    data: { tenant_id: id, name: name || id, environment },
  })
  return okJson(res, `createTenant(${id})`)
}

export async function registerStaff(request, {
  tenantId, role = 'professor', email, password = 'e2e-test-pass-1', name = 'E2E Staff',
} = {}) {
  const staffEmail = email || `${unique('staff')}@e2e.test`
  const res = await request.post('/auth/register', {
    data: { email: staffEmail, password, role, tenant_id: tenantId, name },
  })
  const body = await okJson(res, `registerStaff(${staffEmail})`)
  return { email: staffEmail, password, ...body }
}

export async function staffLogin(request, { email, password }) {
  const res = await request.post('/auth/login', { data: { email, password } })
  return okJson(res, `staffLogin(${email})`)
}

/**
 * Register + log in one call — the common path fixtures want. Keeps
 * email/password on the returned object (the login response alone doesn't
 * carry the password) so callers can re-authenticate through the UI, not
 * just via the token.
 */
export async function provisionStaff(request, { tenantId, role = 'professor', name = 'E2E Staff' } = {}) {
  const { email, password } = await registerStaff(request, { tenantId, role, name })
  const session = await staffLogin(request, { email, password })
  return { ...session, email, password }
}

export async function studentLogin(request, { email, institution, name } = {}) {
  const studentEmail = email || `${unique('student')}@e2e.test`
  const res = await request.post('/student-auth/login', {
    data: { email: studentEmail, institution, name: name || 'E2E Student' },
  })
  return okJson(res, `studentLogin(${studentEmail})`)
}

/**
 * Seed a verified baseline sample for a student. POST /students/{id}/score
 * 422s with zero authenticated samples (see original/api.py), so scoring
 * (and the manifest/audit trail it writes) only happens once a student has
 * at least one baseline sample on file — this is what a real cold-start
 * student would have from an earlier proctored/verified sitting.
 */
export async function addBaselineFor(request, studentId, studentToken, {
  text = 'A baseline writing sample used to seed this e2e student before scoring.',
  provenance = 'verified', assignment = 'E2E baseline seed',
} = {}) {
  const res = await request.post(`/students/${encodeURIComponent(studentId)}/baseline`, {
    headers: { Authorization: `Bearer ${studentToken}` },
    data: { text, provenance, assignment },
  })
  return okJson(res, `addBaselineFor(${studentId})`)
}

export async function createCourse(request, staffToken, { name, code, term = 'E2E' } = {}) {
  const courseName = name || unique('Course')
  const res = await request.post('/bluebook/courses', {
    headers: { Authorization: `Bearer ${staffToken}` },
    data: { name: courseName, code: code || courseName.slice(0, 20), term },
  })
  return okJson(res, `createCourse(${courseName})`)
}

export async function createExam(request, staffToken, {
  title, course, duration = 90, minWords = 12, maxWords = null, prompt = '', status = 'ACTIVE',
} = {}) {
  const examTitle = title || unique('Exam')
  const res = await request.post('/bluebook/exams', {
    headers: { Authorization: `Bearer ${staffToken}` },
    data: { title: examTitle, course, duration, minWords, maxWords, prompt, status },
  })
  return okJson(res, `createExam(${examTitle})`)
}

/**
 * One call: a fresh tenant + a staff login for it.
 *
 * Order matters: /auth/register has no FK check on tenant_id (it'll happily
 * create a user for a tenant that doesn't exist yet), so register+login the
 * staff user first, then use their token to authenticate the tenant-creation
 * call itself — the only order that satisfies the staff-only gate on
 * /tenants under ORIGINAL_ENV=pilot (see createTenant above).
 */
export async function provisionTenantWithStaff(request, { role = 'professor' } = {}) {
  const tenantId = unique('e2e-tenant')
  const staff = await provisionStaff(request, { tenantId, role })
  const tenant = await createTenant(request, { tenantId, authToken: staff.token })
  return { tenant, staff }
}

/** localStorage shape the React app reads for an authenticated staff/operator session — see demo/bluebook/components.jsx. */
export function staffStorageState(baseURL, { token, role, tenant_id }) {
  return {
    cookies: [],
    origins: [{
      origin: baseURL,
      localStorage: [
        { name: 'original_principal_token', value: token },
        { name: 'original_role', value: role },
        { name: 'original_tenant', value: tenant_id },
      ],
    }],
  }
}

/** localStorage shape the React app reads for an authenticated student session — see demo/bluebook/Exam.jsx. */
export function studentStorageState(baseURL, { token, student_id, tenant_id }) {
  return {
    cookies: [],
    origins: [{
      origin: baseURL,
      localStorage: [
        { name: 'original_session_token', value: token },
        { name: 'original_student_id', value: student_id },
        { name: 'original_tenant', value: tenant_id },
      ],
    }],
  }
}
