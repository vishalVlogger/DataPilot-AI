import type { AnalysisSession, AskResponse, ChartResponse, ChartType, CleaningOperation, CleaningPreview, DatasetMetadata, DatasetProfile, DrillDownResponse, Insight, Job, QualityIssue, ReportOptions, SavedAnalysis, VersionList } from "@/types/dataset";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";
let accessToken: string | null = null;
let workspaceId: string | null = null;

export type User = { id:string; email:string; display_name:string; is_active:boolean; created_at:string; last_login_at:string|null };
export type Workspace = { id:string; name:string; slug:string; role:"owner"|"admin"|"member"; owner_user_id:string; plan_code:string; created_at:string; updated_at:string };
export type AuthPayload = { access_token:string; expires_in:number; user:User; workspaces:Workspace[] };
export type Usage = { plan_code:string; datasets:number; storage_bytes:number; analyses_this_month:number; ai_requests_this_month:number; reports_this_month:number; rows_this_month:number; limits:Record<string,number>; percentages:Record<string,number> };
export type Activity = { id:string; activity_type:string; user_id:string|null; resource_id:string|null; details:Record<string,unknown>|null; created_at:string };
export type Dashboard = { usage:Usage; recent_datasets:Array<Record<string,unknown>>; recent_activity:Activity[] };

export function setApiAuth(token: string | null, workspace: string | null) { accessToken = token; workspaceId = workspace; }

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (workspaceId) headers.set("X-Workspace-ID", workspaceId);
  const response = await fetch(path.startsWith("http") ? path : `${API_URL}${path}`, { ...init, headers, credentials:"include" });
  if (response.status === 401 && !path.endsWith("/auth/refresh") && typeof window !== "undefined") window.dispatchEvent(new Event("datapilot:unauthorized"));
  return response;
}

async function parse<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.message ?? "Request failed");
  return payload as T;
}

export async function register(email:string, password:string, displayName:string):Promise<AuthPayload> { return parse(await apiFetch("/auth/register", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email,password,display_name:displayName})})); }
export async function login(email:string, password:string):Promise<AuthPayload> { return parse(await apiFetch("/auth/login", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email,password})})); }
export async function refreshAuth():Promise<AuthPayload> { return parse(await apiFetch("/auth/refresh", {method:"POST"})); }
export async function logout():Promise<void> { const response=await apiFetch("/auth/logout",{method:"POST"}); if(!response.ok) await parse(response); }
export async function getMe():Promise<{user:User;workspaces:Workspace[]}> { return parse(await apiFetch("/auth/me")); }
export async function listWorkspaces():Promise<Workspace[]> { return parse(await apiFetch("/workspaces")); }
export async function updateWorkspace(id:string, values:{name?:string;slug?:string}):Promise<Workspace> { return parse(await apiFetch(`/workspaces/${id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(values)})); }
export async function updateUser(displayName:string):Promise<User> { return parse(await apiFetch("/auth/me",{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({display_name:displayName})})); }
export async function getUsage():Promise<Usage> { return parse(await apiFetch("/usage")); }
export async function getActivity(limit=50,offset=0):Promise<Activity[]> { return parse(await apiFetch(`/activity?limit=${limit}&offset=${offset}`)); }
export async function getDashboard():Promise<Dashboard> { return parse(await apiFetch("/dashboard")); }

export async function inspectWorkbook(file:File):Promise<string[]> { const body=new FormData();body.append("file",file);const result=await parse<{sheets:{name:string}[]}>(await apiFetch("/datasets/inspect",{method:"POST",body}));return result.sheets.map(s=>s.name); }
export async function uploadDataset(file:File,sheetName?:string):Promise<DatasetMetadata> { const body=new FormData();body.append("file",file);if(sheetName)body.append("sheet_name",sheetName);return parse(await apiFetch("/datasets/upload",{method:"POST",body})); }
export async function listDatasets(options:{limit?:number;offset?:number;search?:string;source_type?:string;recently_analyzed?:boolean}={}):Promise<DatasetMetadata[]> { const query=new URLSearchParams();Object.entries(options).forEach(([k,v])=>{if(v!==undefined&&v!=="")query.set(k,String(v));});return parse(await apiFetch(`/datasets${query.size?`?${query}`:""}`)); }
export async function getDataset(id:string):Promise<DatasetMetadata>{return parse(await apiFetch(`/datasets/${id}`));}
export async function renameDataset(id:string,name:string):Promise<DatasetMetadata>{return parse(await apiFetch(`/datasets/${id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({name})}));}
export async function deleteDataset(id:string):Promise<void>{const r=await apiFetch(`/datasets/${id}`,{method:"DELETE"});if(!r.ok)await parse(r);}
export async function getProfile(id:string):Promise<DatasetProfile>{return parse(await apiFetch(`/datasets/${id}/profile`));}
export async function createSession(id:string,title?:string):Promise<AnalysisSession>{return parse(await apiFetch(`/datasets/${id}/sessions`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title})}));}
export async function askDataset(id:string,question:string,sessionId?:string):Promise<AskResponse>{return parse(await apiFetch(`/datasets/${id}/ask`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question,session_id:sessionId})}));}
export async function getInsights(id:string):Promise<Insight[]>{return parse(await apiFetch(`/datasets/${id}/insights`));}
export async function getQuality(id:string):Promise<QualityIssue[]>{return parse(await apiFetch(`/datasets/${id}/quality`));}
export async function createChart(id:string,question:string,chartType?:ChartType,title?:string):Promise<ChartResponse>{return parse(await apiFetch(`/datasets/${id}/chart`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question,chart_type:chartType,title})}));}
export async function getVersions(id:string):Promise<VersionList>{return parse(await apiFetch(`/datasets/${id}/versions`));}
export async function restoreVersion(id:string,version:number):Promise<{profile:DatasetProfile;version:number}>{return parse(await apiFetch(`/datasets/${id}/versions/${version}/restore`,{method:"POST"}));}
export async function generateReport(id:string,options:ReportOptions):Promise<string>{const r=await apiFetch(`/datasets/${id}/report`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(options)});if(!r.ok)await parse(r);return r.text();}
export async function createReportJob(id:string,options:ReportOptions):Promise<{job_id:string;status:string}>{return parse(await apiFetch(`/datasets/${id}/report`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...options,async_job:true})}));}
export async function getJob(id:string):Promise<Job>{return parse(await apiFetch(`/jobs/${id}`));}
export async function downloadJobResult(job:Job):Promise<void>{if(!job.result_reference)return;const r=await apiFetch(`${API_URL.replace(/\/api$/,'')}${job.result_reference}`);if(!r.ok)await parse(r);const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=`DataPilot_Report.${blob.type==="application/pdf"?"pdf":"html"}`;a.click();URL.revokeObjectURL(url);}
export async function listSavedAnalyses(id:string):Promise<SavedAnalysis[]>{return parse(await apiFetch(`/datasets/${id}/saved-analyses`));}
export async function saveAnalysis(id:string,name:string,plan:Record<string,unknown>,chartConfig?:Record<string,unknown>):Promise<SavedAnalysis>{return parse(await apiFetch(`/datasets/${id}/saved-analyses`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name,plan,chart_config:chartConfig})}));}
export async function runSavedAnalysis(id:string):Promise<{plan:Record<string,unknown>;result:unknown;chart_config:Record<string,unknown>|null}>{return parse(await apiFetch(`/saved-analyses/${id}/run`,{method:"POST"}));}
export async function deleteSavedAnalysis(id:string):Promise<void>{const r=await apiFetch(`/saved-analyses/${id}`,{method:"DELETE"});if(!r.ok)await parse(r);}
export async function drillDown(id:string,basePlan:Record<string,unknown>,clickedDimension:string,clickedValue:unknown,nextDimension:string,breadcrumb:string[]):Promise<DrillDownResponse>{return parse(await apiFetch(`/datasets/${id}/drilldown`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({base_plan:basePlan,clicked_dimension:clickedDimension,clicked_value:clickedValue,next_dimension:nextDimension,breadcrumb})}));}
export async function previewCleaning(id:string,operations:CleaningOperation[]):Promise<CleaningPreview>{return parse(await apiFetch(`/datasets/${id}/clean/preview`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({operations})}));}
export async function applyCleaning(id:string,operations:CleaningOperation[]):Promise<{preview:CleaningPreview;profile:DatasetProfile}>{return parse(await apiFetch(`/datasets/${id}/clean/apply`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({operations,confirmed:true})}));}
export async function resetDataset(id:string):Promise<DatasetProfile>{return parse(await apiFetch(`/datasets/${id}/reset`,{method:"POST"}));}
export async function downloadExport(id:string,format:"csv"|"xlsx",version:"current"|"original"="current"):Promise<void>{const r=await apiFetch(`/datasets/${id}/export?format=${format}&version=${version}`);if(!r.ok)await parse(r);const blob=await r.blob(),disposition=r.headers.get("content-disposition")??"",filename=disposition.match(/filename="([^"]+)"/)?.[1]??`dataset.${format}`,url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=filename;a.click();URL.revokeObjectURL(url);}
