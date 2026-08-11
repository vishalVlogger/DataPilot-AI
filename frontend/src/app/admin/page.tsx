"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useAuth } from "@/auth/AuthContext";
import { FeedbackAttachment, FeedbackItem, getAdminDiagnostics, getAdminFeedback, getAdminSummary, getFeedbackAttachment, supportLookup } from "@/services/api";

function Attachment({ feedbackId, attachment }: { feedbackId:string; attachment:FeedbackAttachment }){
  const[url,setUrl]=useState("");
  useEffect(()=>{let objectUrl="";getFeedbackAttachment(feedbackId,attachment.id).then(blob=>{objectUrl=URL.createObjectURL(blob);setUrl(objectUrl);});return()=>{if(objectUrl)URL.revokeObjectURL(objectUrl);};},[feedbackId,attachment.id]);
  if(!url)return <span className="attachment-loading">Loading {attachment.original_filename}…</span>;
  const image=attachment.content_type.startsWith("image/");
  return <a className="admin-attachment" href={url} target={image?"_blank":undefined} download={image?undefined:attachment.original_filename}>{image&&<img src={url} alt={`Feedback attachment ${attachment.original_filename}`}/>}<span>{attachment.original_filename}<small>{(attachment.size/1024).toFixed(1)} KB · {image?"Open preview":"Download"}</small></span></a>;
}

export default function AdminPage(){
  const auth=useAuth();const[summary,setSummary]=useState<Record<string,number>>({}),[diagnostics,setDiagnostics]=useState<Record<string,string|boolean|null>>({}),[feedback,setFeedback]=useState<FeedbackItem[]>([]),[query,setQuery]=useState(""),[results,setResults]=useState<Array<Record<string,unknown>>>([]),[error,setError]=useState("");
  useEffect(()=>{if(auth.user?.is_system_admin)Promise.all([getAdminSummary(),getAdminFeedback(),getAdminDiagnostics()]).then(([a,b,c])=>{setSummary(a);setFeedback(b);setDiagnostics(c);}).catch(reason=>setError(reason instanceof Error?reason.message:"Unable to load admin support"));},[auth.user]);
  async function search(event:FormEvent){event.preventDefault();try{setResults((await supportLookup(query)).results);}catch(reason){setError(reason instanceof Error?reason.message:"Unable to search");}}
  if(auth.loading)return <div className="page-loader">Loading…</div>;if(!auth.user?.is_system_admin)return <div className="simple-page"><h1>Access denied</h1><p>System administrator permission is required.</p><Link href="/">Back</Link></div>;
  return <div className="simple-page"><header><div><p className="eyebrow">SYSTEM ADMIN</p><h1>Beta support</h1><p>Platform and feedback metadata only—no tenant dataset contents.</p></div><Link className="button-link" href="/">Dashboard</Link></header>{error&&<div className="error" role="alert">{error}</div>}<div className="metrics">{Object.entries(summary).map(([key,value])=><article key={key}><span>{key.replaceAll("_"," ")}</span><strong>{value.toLocaleString()}</strong></article>)}</div><section className="panel"><h2>Diagnostics</h2><div className="diagnostic-grid">{Object.entries(diagnostics).map(([key,value])=><div key={key}><span>{key.replaceAll("_"," ")}</span><b>{String(value??"Not attempted")}</b></div>)}</div></section><form className="panel action-form" onSubmit={search}><label className="sr-only" htmlFor="support-search">Support lookup</label><input id="support-search" required minLength={2} value={query} onChange={event=>setQuery(event.target.value)} placeholder="User email, workspace name, or dataset ID"/><button>Search</button></form>{results.length>0&&<pre className="panel">{JSON.stringify(results,null,2)}</pre>}<section className="panel"><h2>Recent feedback</h2><div className="feedback-admin-list">{feedback.map(item=><article key={item.id} className="quality-item"><div><div className="feedback-meta"><span className="status-badge">{item.category.replaceAll("_"," ")}</span><small>{new Date(item.created_at).toLocaleString()}</small></div><h3>{item.message}</h3><p>{item.user_email??"Unknown user"} · {item.workspace_name??item.workspace_id}</p>{item.technical_context&&<details><summary>Technical context</summary><pre>{JSON.stringify(item.technical_context,null,2)}</pre></details>}{item.attachments.length>0&&<div className="admin-attachments">{item.attachments.map(attachment=><Attachment key={attachment.id} feedbackId={item.id} attachment={attachment}/>)}</div>}</div></article>)}</div></section></div>;
}
