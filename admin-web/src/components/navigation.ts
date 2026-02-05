import {
  Activity,
  AlarmClock,
  AppWindow,
  Braces,
  Database,
  HardDrive,
  LayoutDashboard,
  Settings,
  Users,
} from "lucide-react";

export const navItems = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "sessions", label: "Sessions", icon: AppWindow },
  { id: "tools", label: "Tool Runs", icon: Braces },
  { id: "jobs", label: "Scheduled Jobs", icon: AlarmClock },
  { id: "memory", label: "Memory", icon: Database },
  { id: "users", label: "Users", icon: Users },
  { id: "sandbox", label: "Sandbox", icon: HardDrive },
  { id: "settings", label: "Settings", icon: Settings },
  { id: "activity", label: "Activity", icon: Activity },
] as const;

export type NavItemId = (typeof navItems)[number]["id"];
