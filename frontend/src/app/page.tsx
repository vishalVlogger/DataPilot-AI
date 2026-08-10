"use client";

import { FormEvent, useState } from "react";
import { askDataset, getProfile, inspectWorkbook, uploadDataset } from "@/services/api";
import type { AskResponse, DatasetMetadata, DatasetProfile } from "@/types/dataset";

const format = (value: number) => new Intl.NumberFormat().format(value);

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [sheets, setSheets] = useState<string[]>([]);
  const [sheet, setSheet] = useState("");
  const [dataset, setDataset] = useState<DatasetMetadata | null>(null);
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function chooseFile(selected: File | null) {
    setFile(selected); setSheets([]); setSheet(""); setError("");
    if (selected && /\.xlsx?$/i.test(selected.name)) {
      try { const found = await inspectWorkbook(selected); setSheets(found); setSheet(found[0] ?? ""); }
      catch (reason) { setError(reason instanceof Error ? reason.message : "Could not inspect workbook"); }
    }
  }

  async function upload(event: FormEvent) {
    event.preventDefault(); if (!file) return;
    setBusy(true); setError(""); setAnswer(null);
    try { const created = await uploadDataset(file, sheet || undefined); setDataset(created); setProfile(await getProfile(created.id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Upload failed"); }
    finally { setBusy(false); }
  }

  async function ask(event: FormEvent) {
    event.preventDefault(); if (!dataset || !question.trim()) return;
    setBusy(true); setError("");
    try { setAnswer(await askDataset(dataset.id, question)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Analysis failed"); }
    finally { setBusy(false); }
  }

  return <main>
    <aside>
      <div className="brand"><span>DP</span><div>DataPilot <b>AI</b></div></div>
      <nav>{["Dashboard", "Upload Data", "Dataset", "Ask AI", "Insights", "Charts", "Data Quality"].map((item, i) => <a className={i === (dataset ? 2 : 1) ? "active" : ""} key={item}>{item}</a>)}</nav>
      <div className="status"><i /> Local AI mode<br/><small>No API key required</small></div>
    </aside>
    <section className="content">
      <header><div><p className="eyebrow">WORKSPACE</p><h1>{dataset ? dataset.name : "Upload your data"}</h1><p>{dataset ? "Your dataset is ready to explore." : "Turn spreadsheets into clear, calculated answers."}</p></div><div className="avatar">DA</div></header>

      {!dataset && <div className="upload-card">
        <div className="upload-copy"><span className="icon">↥</span><h2>Bring your data aboard</h2><p>Upload a CSV or Excel workbook. Your file stays in local development storage.</p></div>
        <form onSubmit={upload}>
          <label className="dropzone"><input type="file" accept=".csv,.xlsx,.xls" onChange={(e) => chooseFile(e.target.files?.[0] ?? null)} /><b>{file ? file.name : "Choose a file or drop it here"}</b><span>CSV, XLSX or XLS · up to 25 MB</span></label>
          {sheets.length > 0 && <label className="field">Worksheet<select value={sheet} onChange={(e) => setSheet(e.target.value)}>{sheets.map((name) => <option key={name}>{name}</option>)}</select></label>}
          <button disabled={!file || busy}>{busy ? "Analyzing…" : "Upload & analyze"}</button>
        </form>
      </div>}

      {error && <div className="error">{error}</div>}

      {dataset && profile && <>
        <div className="metrics">
          <article><span>Rows</span><strong>{format(profile.row_count)}</strong><small>records analyzed</small></article>
          <article><span>Columns</span><strong>{profile.column_count}</strong><small>{profile.numeric_columns.length} numeric</small></article>
          <article><span>Missing</span><strong>{format(profile.missing_values)}</strong><small>empty cells</small></article>
          <article><span>Duplicates</span><strong>{format(profile.duplicate_rows)}</strong><small>matching rows</small></article>
        </div>

        <div className="grid">
          <article className="panel profile"><div className="panel-title"><div><p className="eyebrow">DATASET PROFILE</p><h2>Columns at a glance</h2></div><button className="secondary" onClick={() => { setDataset(null); setProfile(null); setFile(null); }}>New upload</button></div>
            <div className="table-wrap"><table><thead><tr><th>Column</th><th>Type</th><th>Unique</th><th>Missing</th><th>Summary</th></tr></thead><tbody>{profile.columns.map((column) => <tr key={column.name}><td><b>{column.name}</b></td><td><em className={`pill ${column.category}`}>{column.category}</em></td><td>{format(column.unique_count)}</td><td>{column.missing_percentage}%</td><td>{column.category === "numeric" ? `Σ ${column.sum?.toLocaleString() ?? "—"}` : column.minimum ? `${String(column.minimum).slice(0, 10)} → ${String(column.maximum).slice(0, 10)}` : "—"}</td></tr>)}</tbody></table></div>
          </article>

          <article className="panel ask"><p className="eyebrow">ASK YOUR DATA</p><h2>What would you like to know?</h2><p>Answers are calculated from your uploaded dataset.</p>
            <form onSubmit={ask}><textarea value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={`Try “What is the total ${profile.numeric_columns[0] ?? "revenue"}?”`} /><button disabled={busy || !question.trim()}>{busy ? "Calculating…" : "Ask DataPilot"}</button></form>
            <div className="suggestions">{profile.numeric_columns.slice(0, 1).map((name) => ["total", "average", "maximum"].map((op) => <button key={op} onClick={() => setQuestion(`What is the ${op} ${name}?`)}>{op} {name}</button>))}</div>
            {answer && <div className="answer"><span>CALCULATED ANSWER</span><h3>{answer.answer}</h3>{Array.isArray(answer.result) && <div className="result-list">{answer.result.map((row, index) => <pre key={index}>{JSON.stringify(row)}</pre>)}</div>}</div>}
          </article>
        </div>
      </>}
    </section>
  </main>;
}
