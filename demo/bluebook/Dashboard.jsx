import React from 'react';
import { STOCK_CANDIDATE } from './components.jsx';
import { TeacherFrame } from './TeacherWorkspace.jsx';

// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — Dashboard Screens
//  openExam and the teacher frame
// ════════════════════════════════════════════════════════════════

// Load an exam's config into the shared slot, then enter its briefing
// (the teacher's preview of what students see).
export function openExam(exam, onNavigate) {
  window.BB_EXAM_CONFIG = {
    id:          exam.id,
    title:       exam.title,
    course:      exam.course,
    courseTitle: exam.course,
    duration:    exam.duration || 90,
    minWords:    exam.minWords != null ? exam.minWords : 600,
    maxWords:    exam.maxWords != null ? exam.maxWords : 1200,
    prompt:      exam.prompt || '',
    closesAt:    exam.closes_at || null,
    candidate:   (window.BB_EXAM_CONFIG && window.BB_EXAM_CONFIG.candidate) || STOCK_CANDIDATE,
    ...(exam.conditions || {}),
  };
  onNavigate('briefing');
}

// ─── Dashboard Layout (top bar + content) ────────────────────────────────────
export function DashboardLayout({ activeScreen, onNavigate, children }) {
  return <TeacherFrame active={activeScreen} onNavigate={onNavigate}>{children}</TeacherFrame>;
}
