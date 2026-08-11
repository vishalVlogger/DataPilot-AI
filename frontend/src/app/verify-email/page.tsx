"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { verifyEmail } from "@/services/api";

export default function VerifyEmailPage(){const[message,setMessage]=useState("Verifying your email…"),[error,setError]=useState(""),submitted=useRef(false);useEffect(()=>{if(submitted.current)return;submitted.current=true;const token=new URLSearchParams(window.location.search).get("token");if(!token){setError("The verification token is missing.");return;}verifyEmail(token).then(result=>{setError("");setMessage(result.message);}).catch(reason=>setError(reason instanceof Error?reason.message:"This verification link is invalid or expired."));},[]);return <div className="auth-page"><section className="auth-brand"><div className="brand"><span>DP</span><div>DataPilot <b>AI</b></div></div><p>Email verification protects collaboration and external-provider access.</p></section><section className="auth-card"><p className="eyebrow">EMAIL VERIFICATION</p><h1>{error?"Unable to verify":message}</h1>{error&&<div className="error" role="alert">{error}</div>}<Link className="button-link" href="/login">Continue to sign in</Link></section></div>}
