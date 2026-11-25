import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, FALLBACK_MESSAGE } from "../api/client";
import { SESSION_EXPIRED, useAuth } from "../auth/AuthProvider";
import { Button } from "../components/Button";

export function safeReturn(v: string | null): string {
  if (!v || !v.startsWith("/") || /[\\\s\u0000-\u001f\u007f]/.test(v)) return "/";
  let u: URL;
  try {
    u = new URL(v, window.location.origin);
  } catch {
    return "/";
  }
  if (u.origin !== window.location.origin || !u.pathname.startsWith("/") || u.pathname.startsWith("/masuk")) {
    return "/";
  }
  return u.pathname + u.search + u.hash;
}

export function Login() {
  const { user, login } = useAuth();
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const expired = (location.state as { expired?: boolean } | null)?.expired === true;
  const target = safeReturn(params.get("kembali"));

  if (user && !busy) return <Navigate to={target} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username, password);
      navigate(target, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : FALLBACK_MESSAGE);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <form className="login-card" onSubmit={submit} noValidate>
        <div className="logo login-logo">DigitaDLP</div>
        <h1>Masuk</h1>
        {expired && !error && (
          <p className="notice" role="status">
            {SESSION_EXPIRED}
          </p>
        )}
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}
        <label className="field">
          <span>Nama pengguna</span>
          <input
            name="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </label>
        <label className="field">
          <span>Kata sandi</span>
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        <Button type="submit" variant="primary" disabled={busy || !username || !password}>
          Masuk
        </Button>
      </form>
    </main>
  );
}
