/**
 * tenancy-isolation.spec.mjs — the deliberate cross-tenant negative
 * assertion Stage 0.2 requires before raising `workers` can be trusted
 * (docs/implementation/WS-9-e2e-release-hygiene.md, Stage 0 "Verify").
 *
 * Proves the product's own isolation model (original/principal.py
 * assert_student_access + the per-tenant scoping in the /bluebook/*
 * handlers) keeps one tenant's staff from reading another tenant's data —
 * the same guarantee fixtures/tenancy.mjs relies on to let workers run
 * concurrently without colliding.
 */

import { test, expect } from '@playwright/test'
import { provisionTenantWithStaff, createCourse, createExam } from './fixtures/api-setup.mjs'

test.describe('Cross-tenant isolation (Stage 0.2 verification)', () => {
  test('staff of tenant B cannot read tenant A course/exam by id or listing', async ({ request }) => {
    const a = await provisionTenantWithStaff(request)
    const b = await provisionTenantWithStaff(request)

    const courseA = await createCourse(request, a.staff.token, { name: 'Tenant A Course' })
    const examA = await createExam(request, a.staff.token, { title: 'Tenant A Exam', course: courseA.name })

    // Direct fetch by id is refused
    const getRes = await request.get(`/bluebook/exams/${examA.id}`, {
      headers: { Authorization: `Bearer ${b.staff.token}` },
    })
    expect(getRes.status()).toBe(403)

    // B's exam listing does not leak A's exam
    const examsRes = await request.get('/bluebook/exams', {
      headers: { Authorization: `Bearer ${b.staff.token}` },
    })
    expect(examsRes.ok()).toBe(true)
    const { exams } = await examsRes.json()
    expect(exams.some(e => e.id === examA.id)).toBe(false)

    // B's course listing does not leak A's course
    const coursesRes = await request.get('/bluebook/courses', {
      headers: { Authorization: `Bearer ${b.staff.token}` },
    })
    expect(coursesRes.ok()).toBe(true)
    const { courses } = await coursesRes.json()
    expect(courses.some(c => c.id === courseA.id)).toBe(false)

    // A's own staff can still read their own exam (isolation isn't a blanket denial)
    const ownRes = await request.get(`/bluebook/exams/${examA.id}`, {
      headers: { Authorization: `Bearer ${a.staff.token}` },
    })
    expect(ownRes.ok()).toBe(true)
  })
})
