import type { AnalysisSession, AskResponse, ChartResponse, ChartType, CleaningOperation, CleaningPreview, DatasetMetadata, DatasetProfile, DrillDownResponse, Insight, Job, QualityIssue, ReportOptions, SavedAnalysis, VersionList } from "@/types/dataset";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";
let accessToken: string | null = null;
let workspaceId: string | null = null;

export type User = { id:string; email:string; display_name:string; is_active:boolean; is_system_admin:boolean; email_verified_at:string|null; beta_acknowledged_at:string|null; created_at:string; last_login_at:string|null };
export type Workspace = { id:string; name:string; slug:string; role:"owner"|"admin"|"member"; owner_user_id:string; plan_code:string; external_ai_enabled:boolean; created_at:string; updated_at:string; deletion_requested_at:string|null; deletion_scheduled_for:string|null };
export type AuthPayload = { access_token:string; expires_in:number; user:User; workspaces:Workspace[]; email_delivery_status?:string|null; development_verification_url?:string|null };
export type Usage = { plan_code:string; datasets:number; storage_bytes:number; analyses_this_month:number; ai_requests_this_month:number; reports_this_month:number; rows_this_month:number; limits:Record<string,number>; percentages:Record<string,number> };
export type Activity = { id:string; activity_type:string; user_id:string|null; resource_id:string|null; details:Record<string,unknown>|null; created_at:string };
export type Dashboard = { usage:Usage; recent_datasets:Array<Record<string,unknown>>; recent_activity:Activity[] };
export type Member={user_id:string;email:string;display_name:string;role:"owner"|"admin"|"member";joined_at:string};
export type Invitation={id:string;workspace_id:string;email:string;role:"admin"|"member";invited_by_user_id:string;created_at:string;expires_at:string;accepted_at:string|null;revoked_at:string|null;status:"pending"|"accepted"|"expired"|"revoked";delivery_status?:string|null;development_invitation_url?:string|null};
export type ProviderStatus={app_version:string;configured_provider:string;effective_provider:string;external_ai_enabled:boolean;email_verified:boolean;privacy_notice:string};
export type FeedbackAttachment={id:string;feedback_id:string;original_filename:string;content_type:string;size:number;created_at:string};
export type FeedbackItem={id:string;user_id:string;workspace_id:string;category:string;message:string;current_page?:string|null;dataset_id?:string|null;technical_context?:Record<string,unknown>|null;status:string;priority?:string;created_at:string;user_email?:string|null;workspace_name?:string|null;attachments:FeedbackAttachment[]};

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
  if (!response.ok) { const context={request_id:payload.request_id as string|undefined,route:new URL(response.url).pathname,error_code:payload.error_code as string|undefined,page:typeof window!=="undefined"?window.location.pathname:undefined,occurred_at:Date.now()};if(typeof window!=="undefined")sessionStorage.setItem("datapilot_last_error",JSON.stringify(context));throw new Error(`${payload.message ?? "Request failed"}${payload.request_id?` Reference ID: ${payload.request_id}`:""}`); }
  return payload as T;
}

export async function register(email:string, password:string, displayName:string, invitationToken?:string):Promise<AuthPayload> { return parse(await apiFetch("/auth/register", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email,password,display_name:displayName,invitation_token:invitationToken,beta_acknowledged:true})})); }
export async function login(email:string, password:string):Promise<AuthPayload> { return parse(await apiFetch("/auth/login", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email,password})})); }
export async function refreshAuth():Promise<AuthPayload> { return parse(await apiFetch("/auth/refresh", {method:"POST"})); }
export async function logout():Promise<void> { const response=await apiFetch("/auth/logout",{method:"POST"}); if(!response.ok) await parse(response); }
export async function getMe():Promise<{user:User;workspaces:Workspace[]}> { return parse(await apiFetch("/auth/me")); }
export async function listWorkspaces():Promise<Workspace[]> { return parse(await apiFetch("/workspaces")); }
export async function updateWorkspace(id:string, values:{name?:string;slug?:string;external_ai_enabled?:boolean}):Promise<Workspace> { return parse(await apiFetch(`/workspaces/${id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(values)})); }
export async function exportWorkspace(id:string,includeRawDatasets=false):Promise<{job_id:string;status:string}>{return parse(await apiFetch(`/workspaces/${id}/export`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({include_raw_datasets:includeRawDatasets})}));}
export async function requestWorkspaceDeletion(id:string,confirmation:string):Promise<{deletion_scheduled_for:string}>{return parse(await apiFetch(`/workspaces/${id}/deletion-request`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({confirmation,export_first:false})}));}
export async function cancelWorkspaceDeletion(id:string):Promise<{cancelled:boolean}>{return parse(await apiFetch(`/workspaces/${id}/deletion-request`,{method:"DELETE"}));}
export async function requestAccountDeletion(password:string):Promise<{status:string;requested_at:string}>{return parse(await apiFetch("/auth/deletion-request",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password})}));}
export async function updateUser(displayName:string):Promise<User> { return parse(await apiFetch("/auth/me",{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({display_name:displayName})})); }
export async function verifyEmail(token:string):Promise<{message:string}>{return parse(await apiFetch("/auth/verify-email",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token})}));}
export async function resendVerification():Promise<{message:string;delivery_status:string|null;development_verification_url:string|null}>{return parse(await apiFetch("/auth/resend-verification",{method:"POST"}));}
export async function forgotPassword(email:string):Promise<{message:string}>{return parse(await apiFetch("/auth/forgot-password",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email})}));}
export async function resetPassword(token:string,newPassword:string):Promise<{message:string}>{return parse(await apiFetch("/auth/reset-password",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token,new_password:newPassword})}));}
export async function getUsage():Promise<Usage> { return parse(await apiFetch("/usage")); }
export async function getActivity(limit=50,offset=0):Promise<Activity[]> { return parse(await apiFetch(`/activity?limit=${limit}&offset=${offset}`)); }
export async function getDashboard():Promise<Dashboard> { return parse(await apiFetch("/dashboard")); }
export async function listMembers(id:string):Promise<Member[]>{return parse(await apiFetch(`/workspaces/${id}/members`));}
export async function listInvitations(id:string):Promise<Invitation[]>{return parse(await apiFetch(`/workspaces/${id}/invitations`));}
export async function inviteMember(id:string,email:string,role:"admin"|"member"):Promise<Invitation>{return parse(await apiFetch(`/workspaces/${id}/invitations`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email,role})}));}
export async function resendInvitation(workspaceId:string,invitationId:string):Promise<Invitation>{return parse(await apiFetch(`/workspaces/${workspaceId}/invitations/${invitationId}/resend`,{method:"POST"}));}
export async function revokeInvitation(workspaceId:string,invitationId:string):Promise<void>{const r=await apiFetch(`/workspaces/${workspaceId}/invitations/${invitationId}`,{method:"DELETE"});if(!r.ok)await parse(r);}
export async function updateMemberRole(workspaceId:string,userId:string,role:"admin"|"member"):Promise<Member>{return parse(await apiFetch(`/workspaces/${workspaceId}/members/${userId}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({role})}));}
export async function removeMember(workspaceId:string,userId:string):Promise<void>{const r=await apiFetch(`/workspaces/${workspaceId}/members/${userId}`,{method:"DELETE"});if(!r.ok)await parse(r);}
export async function acceptInvitation(token:string):Promise<Invitation>{return parse(await apiFetch(`/invitations/${encodeURIComponent(token)}/accept`,{method:"POST"}));}
export async function getProviderStatus():Promise<ProviderStatus>{return parse(await apiFetch("/ai/provider-status"));}
export async function submitFeedback(values:{category:string;message:string;current_page?:string;dataset_id?:string;include_technical_context:boolean;request_id?:string;route?:string;error_code?:string;user_agent?:string}):Promise<{id:string}>{return parse(await apiFetch("/feedback",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(values)}));}
export async function getFeedbackConfig():Promise<{max_attachments:number;max_attachment_mb:number;accepted_extensions:string[]}>{return parse(await apiFetch("/feedback/config"));}
export async function uploadFeedbackAttachments(feedbackId:string,files:File[]):Promise<FeedbackAttachment[]>{const body=new FormData();files.forEach(file=>body.append("files",file));return parse(await apiFetch(`/feedback/${feedbackId}/attachments`,{method:"POST",body}));}
export async function getAdminSummary():Promise<Record<string,number>>{return parse(await apiFetch("/admin/summary"));}
export async function getAdminFeedback():Promise<FeedbackItem[]>{return parse(await apiFetch("/admin/feedback"));}
export async function getAdminDiagnostics():Promise<Record<string,string|boolean|null>>{return parse(await apiFetch("/admin/diagnostics"));}
export async function getFeedbackAttachment(feedbackId:string,attachmentId:string):Promise<Blob>{const response=await apiFetch(`/admin/feedback/${feedbackId}/attachments/${attachmentId}`);if(!response.ok)await parse(response);return response.blob();}
export async function supportLookup(query:string):Promise<{results:Array<Record<string,unknown>>}>{return parse(await apiFetch(`/admin/support?q=${encodeURIComponent(query)}`));}
export async function adminGet<T=Record<string,unknown>>(section:string,params:Record<string,string|number|boolean|undefined>={}):Promise<T>{const query=new URLSearchParams();Object.entries(params).forEach(([key,value])=>{if(value!==undefined&&value!=="")query.set(key,String(value));});return parse(await apiFetch(`/admin/${section}${query.size?`?${query}`:""}`));}
export async function adminUserAction(userId:string,action:"activate"|"deactivate"|"grant_admin"|"revoke_admin"):Promise<Record<string,unknown>>{return parse(await apiFetch(`/admin/users/${userId}/actions`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action,confirmed:true})}));}
export async function adminRetryJob(jobId:string):Promise<Record<string,unknown>>{return parse(await apiFetch(`/admin/jobs/${jobId}/retry?confirmed=true`,{method:"POST"}));}
export async function adminUpdateFeedback(feedbackId:string,status:string,priority:string):Promise<Record<string,unknown>>{return parse(await apiFetch(`/admin/feedback/${feedbackId}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({status,priority})}));}

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
