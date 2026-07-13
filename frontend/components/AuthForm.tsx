"use client";

import Link from "next/link";
import {useRouter} from "next/navigation";
import {FormEvent, useState} from "react";

import {api, setToken} from "@/lib/api";

export function AuthForm({mode}: {mode: "login" | "register"}) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const token = await api<{access_token: string}>(`/api/auth/${mode}`, {
        method: "POST",
        body: JSON.stringify({email, password}),
      });
      setToken(token.access_token);
      const workspaces = await api<{id: string}[]>("/api/workspaces");
      router.push(`/w/${workspaces[0].id}/datasets`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  const registering = mode === "register";
  return (
    <main className="auth-shell">
      <form className="auth-card" onSubmit={submit}>
        <div className="brand-mark">E</div>
        <div className="auth-intro">
          <p className="eyebrow">AI Evaluation Hub</p>
          <h1>{registering ? "Create your workspace" : "Welcome back"}</h1>
          <p className="muted">
            {registering
              ? "Bring your datasets, endpoints, and judge keys."
              : "Continue measuring what your AI system actually does."}
          </p>
        </div>
        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {error && <p className="notice error">{error}</p>}
        <button className="primary" disabled={busy}>
          {busy ? "Working…" : registering ? "Create account" : "Sign in"}
        </button>
        <p className="muted centered">
          {registering ? "Already registered?" : "New here?"}{" "}
          <Link href={registering ? "/login" : "/register"}>
            {registering ? "Sign in" : "Create an account"}
          </Link>
        </p>
      </form>
    </main>
  );
}
