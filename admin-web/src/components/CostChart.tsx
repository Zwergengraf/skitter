import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { OverviewCostPoint } from "@/lib/types";

interface CostChartProps {
  data: OverviewCostPoint[];
}

export function CostChart({ data }: CostChartProps) {
  const toTwoDecimals = (value: number | string) => Number(value || 0).toFixed(2);

  if (!data.length) {
    return (
      <div className="flex h-52 items-center justify-center rounded-2xl border border-dashed border-border bg-muted/40 text-sm text-mutedForeground">
        No cost data yet.
      </div>
    );
  }

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <defs>
            <linearGradient id="cost" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#0e7490" stopOpacity={0.35} />
              <stop offset="95%" stopColor="#0e7490" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="label" axisLine={false} tickLine={false} fontSize={12} />
          <YAxis
            axisLine={false}
            tickLine={false}
            fontSize={12}
            width={45}
            tickFormatter={(value: number | string) => toTwoDecimals(value)}
          />
          <Tooltip
            contentStyle={{
              borderRadius: 12,
              border: "1px solid hsl(var(--border))",
              boxShadow: "0 10px 30px hsl(var(--foreground) / 0.15)",
              backgroundColor: "hsl(var(--card))",
              color: "hsl(var(--foreground))",
            }}
            labelStyle={{ color: "hsl(var(--foreground))" }}
            itemStyle={{ color: "hsl(var(--foreground))" }}
            formatter={(value: number | string) => toTwoDecimals(value)}
          />
          <Area type="monotone" dataKey="cost" stroke="#0e7490" fill="url(#cost)" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
