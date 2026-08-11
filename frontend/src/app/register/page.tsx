"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/auth/AuthContext";
import { CopyLink } from "@/components/CopyLink";

export default function RegisterPage() {
  const auth = useAuth(); const router = useRouter();
  const [name, setName] = useState(""), [email, setEmail] = useState(""), [password, setPassword] = useState(""), [accepted, setAccepted] = useState(false);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [verificationUrl, setVerificationUrl] = useState<string | null>(null);
  useEffect(() => { if (!auth.loading && auth.user && !busy && !verificationUrl) router.replace("/"); }, [auth.loading, auth.user, busy, verificationUrl, router]);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const result = await auth.register(email, password, name);
      if (result.development_verification_url) setVerificationUrl(result.development_verification_url);
      else router.replace("/");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to create account"); }
    finally { setBusy(false); }
  }
  if (verificationUrl) return <div className="auth-page"><section className="auth-brand"><div className="brand"><span>DP</span><div>DataPilot <b>AI</b></div></div><p>Your workspace is ready.</p></section><section className="auth-card"><p className="eyebrow">ACCOUNT CREATED</p><h1>Verify your email</h1><p>Console email mode does not send a real message. Use this development-only link to finish verification.</p><CopyLink url={verificationUrl} label="verification link"/><Link className="button-link" href={verificationUrl}>Verify now</Link><Link href="/">Continue to dashboard</Link></section></div>;
  return <div className="auth-page"><section className="auth-brand"><div className="brand"><span>DP</span><div>DataPilot <b>AI</b></div></div><p>Your private analytics workspace is ready in moments.</p></section><form className="auth-card" onSubmit={submit}><p className="eyebrow">GET STARTED</p><h1>Create your account</h1><p>We’ll create your first isolated workspace automatically.</p>{error&&<div className="error" role="alert">{error}</div>}<label>Name<input autoComplete="name" required value={name} onChange={event=>setName(event.target.value)}/></label><label>Email<input type="email" autoComplete="email" required value={email} onChange={event=>setEmail(event.target.value)}/></label><label>Password<input type="password" autoComplete="new-password" minLength={10} required value={password} onChange={event=>setPassword(event.target.value)}/><small>At least 10 characters with letters and numbers.</small></label><label className="check"><input type="checkbox" required checked={accepted} onChange={event=>setAccepted(event.target.checked)}/> I understand DataPilot is a beta: uploaded data is processed for analytics, sensitive or regulated data should be avoided unless approved, and results require review.</label><button disabled={busy||!accepted}>{busy?"Creating workspace…":"Create account"}</button><small>Already have an account? <Link href="/login">Sign in</Link></small></form></div>;
}
