"use client";

import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import type { ChartResponse } from "@/types/dataset";

const colors = ["#3758f9", "#2dcdb2", "#f6a63c", "#ec5f78", "#855cf8", "#40a8e7"];
const fullNumber = new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 });
const compactNumber = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const truncate = (value: unknown, length = 25) => { const text = String(value ?? "—"); return text.length > length ? `${text.slice(0, length - 1)}…` : text; };
const semantic = (value: string | null | undefined) => value ? value.replaceAll("_", " ").replace(/\b\w/g, character => character.toUpperCase()) : "Value";

function ChartTooltip({ active, payload, label, chart }: { active?: boolean; payload?: Array<{ value?: unknown; payload?: Record<string, unknown> }>; label?: unknown; chart: ChartResponse }) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload ?? {};
  const category = row[chart.x_axis] ?? label;
  const metric = row[chart.y_axis] ?? payload[0]?.value;
  return <div className="chart-tooltip"><b>{chart.x_axis_label ?? semantic(chart.x_axis)}</b><span>{String(category ?? "—")}</span><b>{chart.tooltip_label ?? chart.y_axis_label ?? semantic(chart.y_axis)}</b><span>{typeof metric === "number" ? fullNumber.format(metric) : String(metric ?? "—")}</span></div>;
}

export function DataChart({ chart, onPointClick }: { chart: ChartResponse; onPointClick?: (row: Record<string, string | number | null>) => void }) {
  if (!chart.data.length) return <div className="empty-state">No chart data was returned. Try a different question or chart type.</div>;
  const values = chart.data.map(row => String(row[chart.x_axis] ?? ""));
  const longLabels = values.some(value => value.length > 14);
  const tooltip = <Tooltip content={<ChartTooltip chart={chart}/>}/>;
  const numericAxis = { tickFormatter: (value: number) => compactNumber.format(Number(value)), tickMargin: 8 };
  const verticalMargin = { top: 18, right: 28, bottom: longLabels ? 82 : 48, left: 38 };
  const xLabel = chart.x_axis_label ? { value: chart.x_axis_label, position: "insideBottom" as const, offset: longLabels ? -64 : -30 } : undefined;
  const yLabel = chart.y_axis_label ? { value: chart.y_axis_label, angle: -90, position: "insideLeft" as const, offset: -24 } : undefined;
  const aria = `${chart.title}. ${chart.x_axis_label ?? semantic(chart.x_axis)} by ${chart.y_axis_label ?? semantic(chart.y_axis)}.`;

  if (chart.type === "bar") {
    const height = Math.max(330, Math.min(620, chart.data.length * 52 + 90));
    const ranked = chart.data.map((row, index) => ({ ...row, __axisLabel: `${index + 1}. ${truncate(row[chart.x_axis], 34)}` }));
    return <div className="chart-canvas" role="img" aria-label={aria}><ResponsiveContainer width="100%" height={height}><BarChart data={ranked} layout="vertical" margin={{ top: 12, right: 30, bottom: 48, left: 18 }}><CartesianGrid strokeDasharray="3 3" horizontal={false}/><XAxis type="number" {...numericAxis} label={chart.y_axis_label ? { value: chart.y_axis_label, position: "insideBottom", offset: -28 } : undefined}/><YAxis type="category" dataKey="__axisLabel" width={190} tick={{ fontSize: 12 }} tickMargin={10}/>{tooltip}<Bar dataKey={chart.y_axis} name={chart.tooltip_label ?? chart.y_axis_label ?? semantic(chart.y_axis)} fill={colors[0]} radius={[0, 6, 6, 0]} onClick={(entry) => onPointClick?.(entry.payload as Record<string, string | number | null>)}/></BarChart></ResponsiveContainer></div>;
  }
  if (chart.type === "line") return <div className="chart-canvas" role="img" aria-label={aria}><ResponsiveContainer width="100%" height={380}><LineChart data={chart.data} margin={verticalMargin}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey={chart.x_axis} tickFormatter={value => truncate(value, 18)} angle={longLabels ? -25 : 0} textAnchor={longLabels ? "end" : "middle"} height={longLabels ? 75 : 42} tickMargin={10} label={xLabel}/><YAxis {...numericAxis} width={82} label={yLabel}/>{tooltip}{chart.show_legend !== false && <Legend verticalAlign="top"/>}<Line dataKey={chart.y_axis} name={chart.tooltip_label ?? chart.y_axis_label ?? semantic(chart.y_axis)} stroke={colors[0]} strokeWidth={3} dot={{ r: 3 }}/></LineChart></ResponsiveContainer></div>;
  if (chart.type === "pie") return <div className="chart-canvas" role="img" aria-label={aria}><ResponsiveContainer width="100%" height={380}><PieChart><Tooltip content={<ChartTooltip chart={chart}/>}/>{chart.show_legend !== false && <Legend formatter={value => truncate(value, 28)}/>}<Pie data={chart.data} dataKey={chart.y_axis} nameKey={chart.x_axis} outerRadius="72%" label={({ name }) => truncate(name, 16)}>{chart.data.map((_, index) => <Cell key={index} fill={colors[index % colors.length]}/>)}</Pie></PieChart></ResponsiveContainer></div>;
  if (chart.type === "scatter") return <div className="chart-canvas" role="img" aria-label={aria}><ResponsiveContainer width="100%" height={380}><ScatterChart margin={verticalMargin}><CartesianGrid/><XAxis dataKey={chart.x_axis} name={chart.x_axis_label ?? semantic(chart.x_axis)} type="number" {...numericAxis} label={xLabel}/><YAxis dataKey={chart.y_axis} name={chart.y_axis_label ?? semantic(chart.y_axis)} type="number" {...numericAxis} width={82} label={yLabel}/>{tooltip}<Scatter data={chart.data} fill={colors[0]}/></ScatterChart></ResponsiveContainer></div>;
  return <div className="chart-canvas" role="img" aria-label={aria}><ResponsiveContainer width="100%" height={390}><BarChart data={chart.data} margin={verticalMargin}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey={chart.x_axis} tickFormatter={value => truncate(value, 18)} angle={longLabels ? -25 : 0} textAnchor={longLabels ? "end" : "middle"} height={longLabels ? 75 : 42} tickMargin={10} interval={0} label={xLabel}/><YAxis {...numericAxis} width={82} label={yLabel}/>{tooltip}<Bar dataKey={chart.y_axis} name={chart.tooltip_label ?? chart.y_axis_label ?? semantic(chart.y_axis)} fill={colors[0]} radius={[6, 6, 0, 0]} onClick={(entry) => onPointClick?.(entry.payload as Record<string, string | number | null>)}/></BarChart></ResponsiveContainer></div>;
}
