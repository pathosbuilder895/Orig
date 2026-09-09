CREATE TABLE fused_scores (submission_id TEXT PRIMARY KEY, student_id TEXT, fused_log_odds REAL, probability REAL, band TEXT, channels_json TEXT, model_version TEXT, created_at TEXT, baseline_samples INTEGER, reference_profiles INTEGER);
INSERT INTO fused_scores VALUES ('synthetic-1','synthetic-student',-0.1,0.475,'inconclusive','{"compression":0.799,"peer_centered_z":0.1}','v1','2026-08-01',3,7);
INSERT INTO fused_scores VALUES ('synthetic-2','synthetic-student',0.1,0.525,'inconclusive','{"compression":0.780,"peer_centered_z":0.1}','v1','2026-08-02',12,8);
INSERT INTO fused_scores VALUES ('synthetic-3','synthetic-student',0.3,0.574,'inconclusive','{"compression":0.760,"peer_centered_z":0.1}','v1','2026-08-03',24,7);
INSERT INTO fused_scores VALUES ('synthetic-4','synthetic-student',0.5,0.622,'inconclusive','{"compression":0.730,"peer_centered_z":0.1}','v1','2026-08-04',48,8);
CREATE TABLE ai_likelihood_scores (submission_id TEXT PRIMARY KEY, student_id TEXT, probability REAL, band TEXT, model_version TEXT, created_at TEXT);
CREATE TABLE fidelity_scores (submission_id TEXT PRIMARY KEY, student_id TEXT NOT NULL, fidelity REAL NOT NULL, is_authentic INTEGER NOT NULL, created_at TEXT NOT NULL);
INSERT INTO ai_likelihood_scores VALUES ('synthetic-1','synthetic-student',0.1,'low','v1','2026-08-01');
INSERT INTO fidelity_scores VALUES ('synthetic-1','synthetic-student',0.9,1,'2026-08-01');
