/* actions.js — the ONE canonical map from recommendation-action enums to
 * user-facing labels and colors. Every dashboard imports this; no page keeps
 * its own copy. Before this file, "Discuss" meant the mild action on admin
 * and the severest one on professor — a professor and registrar comparing
 * notes were using the same word for different things.
 *
 * Color semantics (fixed product-wide):
 *   green = confirmed · blue = informational/follow-up ·
 *   amber = conversation · wine = needs review · gray = no data yet
 */
(function () {
  'use strict';

  window.ORIGINAL_ACTIONS = {
    no_action:             { label: 'Voice Confirmed',         color: '#4A6B5C' },
    monitor:               { label: 'Follow Up',               color: '#2563EB' },
    schedule_conversation: { label: 'Schedule a Conversation', color: '#D97706' },
    escalate:              { label: 'Needs Review',            color: '#6B2737' },
    no_data:               { label: 'Not Yet Scored',          color: '#9CA3AF' },
  };

  /** Label for an action enum, with a safe fallback. */
  window.originalActionLabel = function (action) {
    const a = window.ORIGINAL_ACTIONS[action];
    return a ? a.label : (action || 'Not Yet Scored');
  };

  /** Color for an action enum, with a safe fallback. */
  window.originalActionColor = function (action) {
    const a = window.ORIGINAL_ACTIONS[action];
    return a ? a.color : '#9CA3AF';
  };
})();
