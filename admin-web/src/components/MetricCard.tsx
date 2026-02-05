import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import type { Metric } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";

interface MetricCardProps {
  metric: Metric;
}

export function MetricCard({ metric }: MetricCardProps) {
  const Icon = metric.trend === "up" ? ArrowUpRight : metric.trend === "down" ? ArrowDownRight : Minus;
  const trendColor =
    metric.trend === "up" ? "text-emerald-600" : metric.trend === "down" ? "text-rose-500" : "text-mutedForeground";

  return (
    <Card className="animate-fade-up">
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between">
          <p className="text-sm text-mutedForeground">{metric.label}</p>
          <span className={`flex items-center gap-1 text-xs font-semibold ${trendColor}`}>
            <Icon className="h-3 w-3" />
            {metric.delta}
          </span>
        </div>
        <div className="text-3xl font-semibold">{metric.value}</div>
        <div className="glow-line h-1 bg-muted" />
      </CardContent>
    </Card>
  );
}
