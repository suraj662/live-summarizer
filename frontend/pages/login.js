import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useState } from "react";

import {
  auth,
  onAuthStateChanged,
  signInWithEmailAndPassword,
} from "../utils/firebase";

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    return onAuthStateChanged(auth, (user) => {
      if (user) router.replace("/");
    });
  }, [router]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);

    try {
      const credential = await signInWithEmailAndPassword(auth, email, password);
      const token = await credential.user.getIdToken();
      window.localStorage.setItem("firebaseIdToken", token);
      window.localStorage.setItem("firebaseUid", credential.user.uid);
      router.replace("/");
    } catch (authError) {
      setError(authError.message || "Unable to sign in.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="auth-page">
      <form onSubmit={handleSubmit} className="auth-card">
        <p className="eyebrow">Live meeting summarizer</p>
        <h1>Welcome back</h1>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
        />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Signing in…" : "Log in"}
        </button>
        <p>
          Need an account? <Link href="/signup">Create one</Link>.
        </p>
      </form>

      <style jsx>{`
        .auth-page { align-items: center; background: #f8fafc; display: flex; justify-content: center; min-height: 100vh; padding: 24px; font-family: Arial, sans-serif; }
        .auth-card { background: white; border: 1px solid #e2e8f0; border-radius: 12px; box-shadow: 0 10px 30px rgb(15 23 42 / 8%); display: grid; gap: 10px; max-width: 380px; padding: 32px; width: 100%; }
        .eyebrow { color: #4f46e5; font-size: 0.8rem; font-weight: 700; letter-spacing: .08em; margin: 0; text-transform: uppercase; }
        h1 { margin: 0 0 10px; }
        input, button { border: 1px solid #cbd5e1; border-radius: 8px; font: inherit; padding: 11px; }
        button { background: #4f46e5; border: 0; color: white; cursor: pointer; margin-top: 10px; }
        button:disabled { background: #94a3b8; cursor: not-allowed; }
        .error { color: #b91c1c; margin: 4px 0; }
      `}</style>
    </main>
  );
}
