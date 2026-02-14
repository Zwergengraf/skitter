import {
  Activity,
  AlarmClock,
  AppWindow,
  Braces,
  Database,
  KeyRound,
  HardDrive,
  LayoutDashboard,
  Settings,
  Users,
  Workflow,
} from "lucide-react";

export const navItems = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "sessions", label: "Sessions", icon: AppWindow },
  { id: "tools", label: "Tool Runs", icon: Braces },
  { id: "agent-jobs", label: "Background Jobs", icon: Workflow },
  { id: "jobs", label: "Scheduled Jobs", icon: AlarmClock },
  { id: "memory", label: "Memory", icon: Database },
  { id: "secrets", label: "Secrets", icon: KeyRound },
  { id: "users", label: "Users", icon: Users },
  { id: "sandbox", label: "Executors", icon: HardDrive },
  { id: "settings", label: "Settings", icon: Settings },
  { id: "activity", label: "Activity", icon: Activity },
] as const;

export type NavItemId = (typeof navItems)[number]["id"];
