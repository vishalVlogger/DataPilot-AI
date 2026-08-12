"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { acceptInvitation, AuthPayload, User, Workspace, login as apiLogin, logout as apiLogout, refreshAuth, register as apiRegister, setApiAuth } from "@/services/api";

type AuthContextValue={user:User|null;workspaces:Workspace[];workspace:Workspace|null;loading:boolean;login:(email:string,password:string)=>Promise<void>;register:(email:string,password:string,name:string)=>Promise<AuthPayload>;logout:()=>Promise<void>;selectWorkspace:(id:string)=>void;refresh:()=>Promise<void>};
const AuthContext=createContext<AuthContextValue|null>(null);

export function AuthProvider({children}:{children:React.ReactNode}){
  const [user,setUser]=useState<User|null>(null),[workspaces,setWorkspaces]=useState<Workspace[]>([]),[workspaceId,setWorkspaceId]=useState<string|null>(null),[loading,setLoading]=useState(true);
  const refreshTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
  const refreshInFlight=useRef<Promise<void>|null>(null);
  function accept(payload:AuthPayload){const preferred=localStorage.getItem("datapilot_workspace");const selected=payload.workspaces.find(w=>w.id===preferred)??payload.workspaces[0]??null;setApiAuth(payload.access_token,selected?.id??null);setUser(payload.user);setWorkspaces(payload.workspaces);setWorkspaceId(selected?.id??null);if(selected)localStorage.setItem("datapilot_workspace",selected.id);if(refreshTimer.current)clearTimeout(refreshTimer.current);refreshTimer.current=setTimeout(()=>void refresh(),Math.max(30,payload.expires_in-60)*1000);}
  function refresh():Promise<void>{
    if(refreshInFlight.current)return refreshInFlight.current;
    const request=(async()=>{try{accept(await refreshAuth());}catch{setApiAuth(null,null);setUser(null);setWorkspaces([]);setWorkspaceId(null);}finally{setLoading(false);}})();
    refreshInFlight.current=request;
    void request.finally(()=>{if(refreshInFlight.current===request)refreshInFlight.current=null;});
    return request;
  }
  useEffect(()=>{void refresh();const unauthorized=()=>void refresh();window.addEventListener("datapilot:unauthorized",unauthorized);return()=>{window.removeEventListener("datapilot:unauthorized",unauthorized);if(refreshTimer.current)clearTimeout(refreshTimer.current);};},[]);
  async function completeSignIn(payload:AuthPayload){accept(payload);const pending=localStorage.getItem("datapilot_pending_invitation");if(pending){await acceptInvitation(pending);localStorage.removeItem("datapilot_pending_invitation");accept(await refreshAuth());}}
  async function login(email:string,password:string){await completeSignIn(await apiLogin(email,password));}
  async function register(email:string,password:string,name:string){const invitation=localStorage.getItem("datapilot_pending_invitation")??undefined;const payload=await apiRegister(email,password,name,invitation);await completeSignIn(payload);return payload;}
  async function logout(){try{await apiLogout();}finally{if(refreshTimer.current)clearTimeout(refreshTimer.current);setApiAuth(null,null);setUser(null);setWorkspaces([]);setWorkspaceId(null);}}
  function selectWorkspace(id:string){if(!workspaces.some(w=>w.id===id))return;setWorkspaceId(id);setApiAuth(null,id);void refresh();localStorage.setItem("datapilot_workspace",id);}
  const value=useMemo(()=>({user,workspaces,workspace:workspaces.find(w=>w.id===workspaceId)??null,loading,login,register,logout,selectWorkspace,refresh}),[user,workspaces,workspaceId,loading]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
export function useAuth(){const value=useContext(AuthContext);if(!value)throw new Error("useAuth must be used within AuthProvider");return value;}
