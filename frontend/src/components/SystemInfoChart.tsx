import React from "react";
import {
  RadialBarChart, RadialBar,
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer
} from "recharts";

type SystemInfo = {
  cpu?: { usage_percent?: number; physical_cores?: number; logical_cores?: number; frequency_mhz?: number };
  memory?: { total_gb?: number; used_gb?: number; percent_used?: number };
  os?: string;
  hostname?: string;
};

function GaugeBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex flex-col items-center">
      <ResponsiveContainer width={100} height={100}>
        <RadialBarChart
          innerRadius="60%" outerRadius="100%"
          startAngle={180} endAngle={0}
          data={[{ value, fill: color }, { value: 100 - value, fill: "#1a1f2e" }]}
        >
          <RadialBar dataKey="value" cornerRadius={4} />
        </RadialBarChart>
      </ResponsiveContainer>
      <div className="text-center -mt-6">
        <div className="text-lg font-bold" style={{ color }}>{value.toFixed(1)}%</div>
        <div className="text-[10px] text-slate-500 uppercase tracking-wider">{label}</div>
      </div>
    </div>
  );
}

function MemoryPie({ used, total }: { used: number; total: number }) {
  const data = [
    { name: "Used", value: used },
    { name: "Free", value: total - used },
  ];
  return (
    <div className="flex flex-col items-center">
      <ResponsiveContainer width={100} height={100}>
        <PieChart>
          <Pie data={data} dataKey="value" innerRadius={28} outerRadius={44} paddingAngle={2}>
            <Cell fill="#1a8cff" />
            <Cell fill="#1a1f2e" />
          </Pie>
          <Tooltip
            contentStyle={{ background: "#0d1117", border: "1px solid #ffffff10", fontSize: 11 }}
            formatter={(v: number) => `${v.toFixed(2)} GB`}
          />
        </PieChart>
      </ResponsiveContainer>
      <div className="text-center -mt-2">
        <div className="text-lg font-bold text-[#1a8cff]">
          {used.toFixed(1)}<span className="text-xs text-slate-500">/{total.toFixed(1)}GB</span>
        </div>
        <div className="text-[10px] text-slate-500 uppercase tracking-wider">Memory</div>
      </div>
    </div>
  );
}

export function SystemInfoChart({ data }: { data: SystemInfo }) {
  const cpuUsage = data.cpu?.usage_percent ?? 0;
  const memPercent = data.memory?.percent_used ?? 0;
  const memUsed = data.memory?.used_gb ?? 0;
  const memTotal = data.memory?.total_gb ?? 0;

  return (
    <div className="bg-[#0d1117] border border-white/5 rounded-xl p-4 my-2">
      <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-3">
        {data.hostname} · {data.os}
      </div>
      <div className="flex gap-6 items-center justify-around">
        <GaugeBar label="CPU" value={cpuUsage} color="#6ee7b7" />
        <GaugeBar label="RAM %" value={memPercent} color="#fcd34d" />
        <MemoryPie used={memUsed} total={memTotal} />
        <div className="text-xs text-slate-400 space-y-1.5">
          <div><span className="text-slate-600">Cores</span> {data.cpu?.physical_cores}P / {data.cpu?.logical_cores}L</div>
          <div><span className="text-slate-600">Freq</span> {data.cpu?.frequency_mhz} MHz</div>
          <div><span className="text-slate-600">Avail</span> {(memTotal - memUsed).toFixed(2)} GB</div>
        </div>
      </div>
    </div>
  );
}