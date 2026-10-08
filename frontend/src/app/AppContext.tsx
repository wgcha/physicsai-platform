import { createContext, useContext } from "react";
import type { Me, Project, Role, StatusInfo } from "../api";

export interface AppContextValue {
  me: Me;
  projects: Project[];
  status: StatusInfo | null;
}

export const AppContext = createContext<AppContextValue | null>(null);

export function useApp(): AppContextValue {
  const v = useContext(AppContext);
  if (!v) throw new Error("AppContext 없음");
  return v;
}

/** 계약 §5.3 role(p) */
export function roleIn(me: Me, projectId: string | undefined): Role | null {
  if (me.is_global_admin) return "admin";
  if (!projectId) return null;
  return me.roles[projectId] ?? null;
}

export function canExecuteIn(me: Me, projectId: string | undefined): boolean {
  const r = roleIn(me, projectId);
  return r === "power" || r === "admin";
}
