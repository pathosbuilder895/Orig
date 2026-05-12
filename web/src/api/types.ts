export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface UserResponse {
  id: string;
  email: string;
  full_name: string;
  role: string;
  institution_id: string;
  is_active: boolean;
  created_at: string;
}

export interface StudentResponse {
  id: string;
  external_id: string;
  full_name: string;
  email: string;
  institution_id: string;
  baseline_sample_count: number;
  last_submission_at: string | null;
  baseline_confidence?: number | null;
}

export interface ScoreResponse {
  submission_id: string;
  student_id: string;
  status: string;
  deviation_score: number;
  authorship_probability: number;
  recommended_action: string;
  rationale: string;
  baseline_confidence: Record<string, unknown>;
  interference: Record<string, unknown>;
  feature_vector: Record<string, number>;
  baseline_vector: Record<string, number>;
  model_version: string;
  scored_at: string;
}

export interface StudentList {
  items: StudentResponse[];
  total: number;
  skip: number;
  limit: number;
}

export interface StudentStateResponse {
  student_id: string;
  sample_count: number;
  authenticated_count: number;
  purity: number;
  trajectory_direction: string;
  trajectory_confidence: number;
  effective_sample_count: number;
  last_updated: string;
}
