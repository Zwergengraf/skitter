import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { OverviewCostPoint } from "@/lib/types";

interface CostChartProps {
  data: OverviewCostPoint[];
}

export function CostChart({ data }: CostChartProps) {
  if (!data.length) {
    return (
      <div className="flex h-52 items-center justify-center rounded-2xl border border-dashed border-border bg-muted/40 text-sm text-mutedForeground">
        No cost data yet.
      </div>
    );
  }

  return (
    <div className="h-52 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <defs>
            <linearGradient id="cost" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#0e7490" stopOpacity={0.35} />
              <stop offset="95%" stopColor="#0e7490" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="label" axisLine={false} tickLine={false} fontSize={12} />
          <YAxis axisLine={false} tickLine={false} fontSize={12} width={30} />
          <Tooltip
            contentStyle={{
              borderRadius: 12,
              border: "1px solid rgba(15,23,42,0.1)",
              boxShadow: "0 8px 24px rgba(15,23,42,0.12)",
            }}
          />
          <Area type="monotone" dataKey="cost" stroke="#0e7490" fill="url(#cost)" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
