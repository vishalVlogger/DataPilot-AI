"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/auth/AuthContext";
import {
  getFeedbackConfig,
  getMyFeedback,
  FeedbackItem,
  submitFeedback,
  uploadFeedbackAttachments,
} from "@/services/api";

export default function FeedbackPage() {
  const auth = useAuth(),
    router = useRouter(),
    fileInput = useRef<HTMLInputElement>(null);
  type ErrorContext = {
    request_id?: string;
    route?: string;
    error_code?: string;
    page?: string;
    occurred_at?: number;
  };
  const [category, setCategory] = useState("general"),
    [featureArea, setFeatureArea] = useState("other"),
    [severity, setSeverity] = useState("medium"),
    [affectedFlow, setAffectedFlow] = useState(""),
    [message, setMessage] = useState(""),
    [technical, setTechnical] = useState(true),
    [files, setFiles] = useState<File[]>([]);
  const [limits, setLimits] = useState({
      max_attachments: 3,
      max_attachment_mb: 5,
      accepted_extensions: [
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".pdf",
        ".txt",
        ".log",
      ],
    }),
    [success, setSuccess] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [recentError, setRecentError] = useState<ErrorContext | null>(null);
  const [submitted, setSubmitted] = useState<FeedbackItem[]>([]);
  useEffect(() => {
    if (!auth.loading && !auth.user) router.replace("/login");
    if (auth.user)
      Promise.all([getFeedbackConfig(), getMyFeedback()])
        .then(([config, feedback]) => { setLimits(config); setSubmitted(feedback); })
        .catch(() => undefined);
    const raw = sessionStorage.getItem("datapilot_last_error");
    if (raw)
      try {
        const context = JSON.parse(raw) as ErrorContext;
        if (
          context.occurred_at &&
          Date.now() - context.occurred_at <= 15 * 60 * 1000
        )
          setRecentError(context);
        else sessionStorage.removeItem("datapilot_last_error");
      } catch {
        sessionStorage.removeItem("datapilot_last_error");
      }
  }, [auth.loading, auth.user, router]);
  function choose(selected: FileList | null) {
    if (!selected) return;
    const next = [...files, ...Array.from(selected)];
    if (next.length > limits.max_attachments) {
      setError(`You can attach up to ${limits.max_attachments} files.`);
      return;
    }
    const invalid = next.find(
      (file) =>
        file.size > limits.max_attachment_mb * 1024 * 1024 ||
        !limits.accepted_extensions.some((extension) =>
          file.name.toLowerCase().endsWith(extension),
        ),
    );
    if (invalid) {
      setError(
        `${invalid.name} is unsupported or larger than ${limits.max_attachment_mb} MB.`,
      );
      return;
    }
    setFiles(next);
    setError("");
    if (fileInput.current) fileInput.current.value = "";
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setSuccess("");
    setBusy(true);
    let feedbackId = "";
    try {
      const created = await submitFeedback({
        category,
        message,
        feature_area: featureArea,
        severity,
        affected_flow: affectedFlow || undefined,
        current_page: window.location.pathname,
        include_technical_context: technical,
        request_id: technical ? recentError?.request_id : undefined,
        route: technical ? recentError?.route : undefined,
        error_code: technical ? recentError?.error_code : undefined,
        user_agent: navigator.userAgent,
      });
      feedbackId = created.id;
      if (files.length) await uploadFeedbackAttachments(created.id, files);
      setMessage("");
      setFiles([]);
      setRecentError(null);
      sessionStorage.removeItem("datapilot_last_error");
      setSuccess("Thanks—your beta feedback and attachments were submitted.");
      setSubmitted(await getMyFeedback());
    } catch (reason) {
      const detail =
        reason instanceof Error ? reason.message : "Unable to send feedback";
      setError(
        feedbackId
          ? `Feedback was saved, but an attachment failed. ${detail}`
          : detail,
      );
    } finally {
      setBusy(false);
    }
  }
  if (auth.loading || !auth.user)
    return <div className="page-loader">Loading feedback…</div>;
  return (
    <div className="simple-page">
      <header>
        <div>
          <p className="eyebrow">BETA FEEDBACK</p>
          <h1>Send Feedback</h1>
          <p>
            Report a bug, UI problem, feature request, or confusing result.
            Dataset contents are never attached automatically.
          </p>
        </div>
        <Link className="button-link" href="/">
          Dashboard
        </Link>
      </header>
      {success && (
        <div className="success-banner" role="status">
          {success}
        </div>
      )}
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <section className="feedback-history panel" aria-labelledby="feedback-history-title">
        <div className="feedback-history-heading">
          <div><p className="eyebrow">YOUR REQUESTS</p><h2 id="feedback-history-title">Feedback status</h2></div>
          <small>We’ll notify you here and by email when an item is resolved.</small>
        </div>
        {submitted.length ? <div className="feedback-history-list">{submitted.map((item) => (
          <article key={item.id} className={item.status === "resolved" ? "resolved" : ""}>
            <div><span className={`status-badge ${item.status}`}>{item.status}</span><time>{new Date(item.created_at).toLocaleDateString()}</time></div>
            <p>{item.message}</p>
            {item.resolved_at && <small>Resolved {new Date(item.resolved_at).toLocaleString()}</small>}
          </article>
        ))}</div> : <div className="empty-state">You haven’t submitted feedback in this workspace yet.</div>}
      </section>
      <form className="panel settings-form" onSubmit={submit}>
        <label>
          Category
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value)}
          >
            <option value="bug">Bug</option>
            <option value="feature_request">Feature request</option>
            <option value="confusing_result">Confusing result</option>
            <option value="general">General feedback</option>
          </select>
        </label>
        <div className="feedback-classification">
          <label>
            Feature area
            <select
              value={featureArea}
              onChange={(event) => setFeatureArea(event.target.value)}
            >
              {[
                "onboarding",
                "datasets",
                "analysis",
                "insights",
                "charts",
                "cleaning",
                "reports",
                "exports",
                "collaboration",
                "account",
                "other",
              ].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
          <label>
            Severity
            <select
              value={severity}
              onChange={(event) => setSeverity(event.target.value)}
            >
              {["low", "medium", "high", "critical"].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
        </div>
        <label>
          Affected flow (optional)
          <input
            value={affectedFlow}
            maxLength={80}
            onChange={(event) => setAffectedFlow(event.target.value)}
            placeholder="For example: first upload or report download"
          />
        </label>
        <label>
          Message
          <textarea
            required
            minLength={3}
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            aria-describedby="feedback-help"
          />
        </label>
        <small id="feedback-help">
          Describe what happened, what you expected, and how we can reproduce
          it.
        </small>
        <label>
          Attach screenshots or files
          <input
            ref={fileInput}
            type="file"
            multiple
            accept={limits.accepted_extensions.join(",")}
            onChange={(event) => choose(event.target.files)}
          />
          <small>
            Up to {limits.max_attachments} files, {limits.max_attachment_mb} MB
            each. PNG, JPG, WebP, PDF, TXT, or LOG.
          </small>
        </label>
        {files.length > 0 && (
          <div className="attachment-list" aria-label="Selected attachments">
            {files.map((file, index) => (
              <div key={`${file.name}-${index}`}>
                <span>
                  {file.name}
                  <small>{(file.size / 1024).toFixed(1)} KB</small>
                </span>
                <button
                  type="button"
                  className="secondary"
                  aria-label={`Remove ${file.name}`}
                  onClick={() =>
                    setFiles((current) =>
                      current.filter((_, itemIndex) => itemIndex !== index),
                    )
                  }
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}
        <label className="check">
          <input
            type="checkbox"
            checked={technical}
            onChange={(event) => setTechnical(event.target.checked)}
          />{" "}
          Include app version, current page, browser, and recent error
          reference. No raw dataset values.
        </label>
        {technical && recentError && (
          <div className="technical-context-preview">
            <span>Recent error to include</span>
            <code>
              {recentError.error_code ?? "Request error"} ·{" "}
              {recentError.route ?? recentError.page ?? "Unknown route"}
            </code>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setRecentError(null);
                sessionStorage.removeItem("datapilot_last_error");
              }}
            >
              Remove error context
            </button>
          </div>
        )}
        <button disabled={busy}>
          {busy ? "Submitting…" : "Submit feedback"}
        </button>
      </form>
    </div>
  );
}
