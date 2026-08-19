export type UserRole = "owner" | "user" | "merchant";

export interface Account {
  id: string;
  username: string;
  role: UserRole;
  full_name: string;
  email: string | null;
  phone: string | null;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
  updated_at: string;
}

export interface LoginInput { username: string; password: string }

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  access_expires_in: number;
}

export interface ValidationIssue {
  loc?: Array<string | number>;
  msg?: string;
  type?: string;
}
