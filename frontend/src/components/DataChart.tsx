"use client";

import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import type { ChartResponse } from "@/types/dataset";

const colors = ["#3758f9", "#2dcdb2", "#f6a63c", "#ec5f78", "#855cf8", "#40a8e7"];

export function DataChart({ chart }: { chart: ChartResponse }) {
  const common = { data: chart.data, margin: { top: 12, right: 18, bottom: 12, left: 5 } };
  if (!chart.data.length) return <div className="empty-state">No chart data was returned.</div>;
  if (chart.type === "line") return <ResponsiveContainer width="100%" height={330}><LineChart {...common}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey={chart.x_axis} label={chart.x_axis_label ? { value: chart.x_axis_label, position: "insideBottom", offset: -6 } : undefined}/><YAxis label={chart.y_axis_label ? { value: chart.y_axis_label, angle: -90, position: "insideLeft" } : undefined}/><Tooltip/>{chart.show_legend !== false && <Legend/>}<Line dataKey={chart.y_axis} stroke={colors[0]} strokeWidth={3} dot={{ r: 3 }}/></LineChart></ResponsiveContainer>;
  if (chart.type === "pie") return <ResponsiveContainer width="100%" height={330}><PieChart><Tooltip/>{chart.show_legend !== false && <Legend/>}<Pie data={chart.data} dataKey={chart.y_axis} nameKey={chart.x_axis} outerRadius={115} label>{chart.data.map((_, index) => <Cell key={index} fill={colors[index % colors.length]}/>)}</Pie></PieChart></ResponsiveContainer>;
  if (chart.type === "scatter") return <ResponsiveContainer width="100%" height={330}><ScatterChart margin={common.margin}><CartesianGrid/><XAxis dataKey={chart.x_axis} name={chart.x_axis} type="number"/><YAxis dataKey={chart.y_axis} name={chart.y_axis} type="number"/><Tooltip cursor={{ strokeDasharray: "3 3" }}/><Scatter data={chart.data} fill={colors[0]}/></ScatterChart></ResponsiveContainer>;
  return <ResponsiveContainer width="100%" height={330}><BarChart {...common}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey={chart.x_axis}/><YAxis/><Tooltip/><Bar dataKey={chart.y_axis} fill={colors[0]} radius={[6, 6, 0, 0]}/></BarChart></ResponsiveContainer>;
}
