"use client";

import { useState } from "react";

export function CopyLink({ url, label }: { url: string; label: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(url);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }
  return <div className="development-link"><p><b>Development email mode is enabled.</b> No real email is sent.</p><input aria-label={`${label} URL`} readOnly value={url}/><button type="button" className="secondary" onClick={copy}>{copied ? "Copied" : `Copy ${label}`}</button></div>;
}
