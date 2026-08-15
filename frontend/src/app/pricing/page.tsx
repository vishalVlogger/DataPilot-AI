"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/auth/AuthContext";
import { getPlans, getSubscription, PublicPlan, requestUpgrade, startTrial, SubscriptionState } from "@/services/api";

const comparisons: Array<[string,string,"limit"|"feature"]> = [
  ["Datasets","datasets","limit"], ["Upload size","upload_bytes","limit"], ["Rows per dataset","rows_per_dataset","limit"],
  ["Monthly analyses","analyses_per_month","limit"], ["Monthly reports","reports_per_month","limit"], ["External AI","external_ai","feature"],
  ["Workspace members","workspace_members","limit"], ["Storage","storage_bytes","limit"], ["Workspace export","workspace_export","feature"],
];

function compact(value:number,key:string){if(key.includes("bytes")){const mb=value/1024/1024;return mb>=1024?`${Number((mb/1024).toFixed(1))} GB`:`${Number(mb.toFixed(0))} MB`;}return value.toLocaleString();}
function price(plan:PublicPlan){if(!plan.price.configured)return plan.code==="business"?"Contact us":"Pricing coming soon";if(plan.price.monthly===0)return "Free";try{return `${new Intl.NumberFormat(undefined,{style:"currency",currency:plan.price.currency,maximumFractionDigits:0}).format(plan.price.monthly!)} / month`;}catch{return `${plan.price.monthly} ${plan.price.currency} / month`;}}

export default function PricingPage(){
  const auth=useAuth();const[plans,setPlans]=useState<PublicPlan[]>([]),[subscription,setSubscription]=useState<SubscriptionState|null>(null),[busy,setBusy]=useState(""),[message,setMessage]=useState(""),[error,setError]=useState("");
  async function load(){const catalog=await getPlans();setPlans(catalog.plans);if(auth.workspace)setSubscription(await getSubscription(auth.workspace.id));}
  useEffect(()=>{void load().catch(reason=>setError(reason instanceof Error?reason.message:"Unable to load plans."));},[auth.workspace?.id]);
  async function act(plan:PublicPlan){if(!auth.user||!auth.workspace)return;setBusy(plan.code);setError("");try{if(plan.code==="pro"&&subscription?.trial.eligible){await startTrial(auth.workspace.id);setMessage("Your Pro trial is active.");}else{await requestUpgrade(auth.workspace.id,plan.code as "pro"|"business");setMessage(`${plan.name} upgrade request sent.`);}await load();}catch(reason){setError(reason instanceof Error?reason.message:"Unable to update your plan.");}finally{setBusy("");}}
  const effective=subscription?.effective_plan.code??auth.workspace?.plan_code;
  return <div className="pricing-page"><header className="pricing-header"><Link className="brand" href="/"><span>DP</span><div>DataPilot <b>AI</b></div></Link><nav><Link href="/">Dashboard</Link>{auth.user?<Link href="/settings">Settings</Link>:<><Link href="/login">Sign in</Link><Link className="button-link" href="/register">Start free</Link></>}</nav></header>
    <main><section className="pricing-hero"><p className="eyebrow">PLANS & ENTITLEMENTS</p><h1>Choose the capacity your work needs</h1><p>Start with deterministic analysis on Free. Trials and upgrade requests work without payment details while beta pricing is validated.</p></section>
    {message&&<div className="success-banner" role="status">{message}</div>}{error&&<div className="error" role="alert">{error}</div>}
    <section className="pricing-cards" aria-label="DataPilot plans">{plans.map(plan=><article key={plan.code} className={effective===plan.code?"current":""}>{effective===plan.code&&<span className="current-plan">Your current plan</span>}<p className="eyebrow">{plan.name.toUpperCase()}</p><h2>{price(plan)}</h2><p>{plan.description}</p><ul>{comparisons.slice(0,5).map(([label,key])=><li key={key}><span>✓</span>{label}: <b>{compact(plan.limits[key],key)}</b></li>)}</ul>{effective===plan.code?<button disabled>Current plan</button>:auth.user&&auth.workspace&&auth.workspace.role==="owner"&&plan.upgrade_order>(subscription?.effective_plan.upgrade_order??-1)?<button disabled={busy===plan.code} onClick={()=>void act(plan)}>{busy===plan.code?"Working…":plan.code==="pro"&&subscription?.trial.eligible?"Start Pro trial":plan.code==="business"?"Request Business":"Request upgrade"}</button>:!auth.user?<Link className="pricing-cta" href="/register">Start free</Link>:null}</article>)}</section>
    <section className="pricing-comparison panel"><div><p className="eyebrow">COMPARE PLANS</p><h2>Entitlements at a glance</h2></div><div className="pricing-table-wrap"><table><thead><tr><th>Capability</th>{plans.map(plan=><th key={plan.code}>{plan.name}</th>)}</tr></thead><tbody>{comparisons.map(([label,key,type])=><tr key={key}><th>{label}</th>{plans.map(plan=><td key={plan.code}>{type==="feature"?(plan.features.includes(key)?"Included":"Not included"):compact(plan.limits[key],key)}</td>)}</tr>)}</tbody></table></div></section>
    <p className="pricing-note">Existing data is never deleted when a trial or assignment ends. If usage exceeds the resulting allowance, existing content stays accessible while new creation may be restricted.</p></main></div>;
}
