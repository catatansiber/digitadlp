export type Role = "pengunggah" | "pemeriksa" | "admin";

/** Bentuk respons GET /api/auth/me dan POST /api/auth/login. */
export type Me = {
  id: number;
  full_name: string;
  role: Role;
  unit: string;
};
