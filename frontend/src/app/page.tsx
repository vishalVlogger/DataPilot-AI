"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/auth/AuthContext";
import { DataChart } from "@/components/DataChart";
import { NotificationBell } from "@/components/NotificationBell";
import {
  applyCleaning,
  askDataset,
  createChart,
  createReportJob,
  createSession,
  deleteDataset,
  deleteSavedAnalysis,
  dismissOnboarding,
  downloadExport,
  downloadJobResult,
  drillDown,
  getDashboard,
  getDataset,
  getInsights,
  getJob,
  getOnboarding,
  getProfile,
  getQuestionExamples,
  getQuality,
  getVersions,
  inspectWorkbook,
  listDatasets,
  listSavedAnalyses,
  loadSampleDataset,
  previewCleaning,
  renameDataset,
  rateAnalysis,
  resetDataset,
  restoreVersion,
  runSavedAnalysis,
  saveAnalysis,
  uploadDataset,
  type Dashboard,
  type OnboardingState,
} from "@/services/api";
import type {
  AskResponse,
  ChartResponse,
  ChartType,
  CleaningOperation,
  CleaningPreview,
  CleaningType,
  DatasetMetadata,
  DatasetProfile,
  DatasetVersion,
  Insight,
  Job,
  QualityIssue,
  ReportOptions,
  SavedAnalysis,
} from "@/types/dataset";

const format = (value: number) => new Intl.NumberFormat().format(value);
const tabs = [
  "Overview",
  "Ask Data",
  "Insights",
  "Charts",
  "Data Quality",
  "Clean",
  "Versions",
  "Saved Analyses",
  "Reports",
  "Export",
] as const;
type Tab = (typeof tabs)[number];

export default function Home() {
  const auth = useAuth();
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null),
    [sheets, setSheets] = useState<string[]>([]),
    [sheet, setSheet] = useState("");
  const [dataset, setDataset] = useState<DatasetMetadata | null>(null),
    [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [active, setActive] = useState<Tab>("Overview"),
    [question, setQuestion] = useState(""),
    [answer, setAnswer] = useState<AskResponse | null>(null);
  const [insights, setInsights] = useState<Insight[]>([]),
    [quality, setQuality] = useState<QualityIssue[]>([]);
  const [chartQuestion, setChartQuestion] = useState(""),
    [chartType, setChartType] = useState<ChartType | "auto">("auto"),
    [chart, setChart] = useState<ChartResponse | null>(null);
  const [cleanType, setCleanType] = useState<CleaningType>("trim_whitespace"),
    [cleanColumn, setCleanColumn] = useState(""),
    [fillValue, setFillValue] = useState("");
  const [cleanOperation, setCleanOperation] =
      useState<CleaningOperation | null>(null),
    [preview, setPreview] = useState<CleaningPreview | null>(null);
  const [versions, setVersions] = useState<DatasetVersion[]>([]);
  const [library, setLibrary] = useState<DatasetMetadata[]>([]),
    [savedAnalyses, setSavedAnalyses] = useState<SavedAnalysis[]>([]),
    [sessionId, setSessionId] = useState<string>();
  const [savedName, setSavedName] = useState(""),
    [job, setJob] = useState<Job | null>(null),
    [breadcrumb, setBreadcrumb] = useState<string[]>([]),
    [nextDimension, setNextDimension] = useState("");
  const [reportOptions, setReportOptions] = useState<ReportOptions>({
    title: "DataPilot AI Analysis Report",
    include_profile: true,
    include_insights: true,
    include_quality: true,
    include_charts: true,
    include_version_history: true,
    format: "pdf",
    async_job: true,
  });
  const [reportBusy, setReportBusy] = useState(false),
    [chartTitle, setChartTitle] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [planLimit, setPlanLimit] = useState(false),
    [chartBusy, setChartBusy] = useState(false),
    [chartError, setChartError] = useState(""),
    [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [onboarding, setOnboarding] = useState<OnboardingState | null>(null);
  const [questionExamples, setQuestionExamples] = useState<string[]>([]);
  const [resultRating, setResultRating] = useState<"yes" | "no" | null>(null);
  const [librarySearch, setLibrarySearch] = useState(""),
    [libraryType, setLibraryType] = useState(""),
    [recentlyAnalyzed, setRecentlyAnalyzed] = useState(false),
    [libraryOffset, setLibraryOffset] = useState(0),
    [hasMore, setHasMore] = useState(false);

  useEffect(() => {
    if (!auth.loading && !auth.user) router.replace("/login");
  }, [auth.loading, auth.user, router]);
  useEffect(() => {
    if (auth.user && auth.workspace)
      Promise.all([
        listDatasets({ limit: 10 }),
        getDashboard(),
        getOnboarding(),
      ])
        .then(([items, summary, progress]) => {
          setLibrary(items);
          setHasMore(items.length === 10);
          setLibraryOffset(0);
          setDashboard(summary);
          setOnboarding(progress);
        })
        .catch(fail);
  }, [auth.user, auth.workspace?.id]);

  async function chooseFile(selected: File | null) {
    setFile(selected);
    setSheets([]);
    setSheet("");
    setError("");
    if (selected && /\.xlsx?$/i.test(selected.name))
      try {
        const found = await inspectWorkbook(selected);
        setSheets(found);
        setSheet(found[0] ?? "");
      } catch (reason) {
        fail(reason);
      }
  }
  function fail(reason: unknown) {
    setPlanLimit(Boolean(reason instanceof Error && (reason as Error & {upgrade_recommended?:boolean}).upgrade_recommended));
    setError(reason instanceof Error ? reason.message : "The request failed");
  }
  async function refreshSupporting(id: string) {
    const [foundInsights, foundQuality, foundVersions, foundSaved] =
      await Promise.all([
        getInsights(id),
        getQuality(id),
        getVersions(id),
        listSavedAnalyses(id),
      ]);
    setInsights(foundInsights);
    setQuality(foundQuality);
    setVersions(foundVersions.versions);
    setSavedAnalyses(foundSaved);
  }
  async function selectDataset(created: DatasetMetadata) {
    const foundProfile = await getProfile(created.id);
    setDataset(created);
    setProfile(foundProfile);
    setCleanColumn(
      foundProfile.categorical_columns[0] ??
        foundProfile.numeric_columns[0] ??
        foundProfile.columns[0]?.name ??
        "",
    );
    setNextDimension(
      foundProfile.categorical_columns[1] ??
        foundProfile.categorical_columns[0] ??
        "",
    );
    const session = await createSession(created.id, "Interactive analysis");
    setSessionId(session.id);
    await refreshSupporting(created.id);
    setQuestionExamples((await getQuestionExamples(created.id)).examples);
  }
  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const created = await uploadDataset(file, sheet || undefined);
      await selectDataset(created);
      setLibrary(await listDatasets());
    } catch (reason) {
      fail(reason);
    } finally {
      setBusy(false);
    }
  }
  async function trySample() {
    setBusy(true);
    setError("");
    try {
      const created = await loadSampleDataset();
      await selectDataset(created);
      setLibrary(await listDatasets());
      setOnboarding(await getOnboarding());
    } catch (reason) {
      fail(reason);
    } finally {
      setBusy(false);
    }
  }
  async function dismissGuide() {
    try {
      await dismissOnboarding();
      setOnboarding((current) =>
        current ? { ...current, dismissed: true } : current,
      );
    } catch (reason) {
      fail(reason);
    }
  }
  async function rateCurrent(helpful: boolean) {
    const runId = answer?.metadata?.run_id;
    if (!runId) return;
    try {
      await rateAnalysis(runId, helpful);
      setResultRating(helpful ? "yes" : "no");
    } catch (reason) {
      fail(reason);
    }
  }
  async function openDataset(id: string) {
    setBusy(true);
    try {
      await selectDataset(await getDataset(id));
    } catch (reason) {
      fail(reason);
    } finally {
      setBusy(false);
    }
  }
  async function removeDataset(id: string) {
    if (
      !window.confirm(
        "Delete this dataset and all of its versions, sessions, saved analyses, and reports?",
      )
    )
      return;
    try {
      await deleteDataset(id);
      setLibrary(await listDatasets());
      if (dataset?.id === id) {
        setDataset(null);
        setProfile(null);
      }
    } catch (reason) {
      fail(reason);
    }
  }
  async function searchLibrary(offset = 0) {
    try {
      const items = await listDatasets({
        limit: 10,
        offset,
        search: librarySearch,
        source_type: libraryType,
        recently_analyzed: recentlyAnalyzed,
      });
      setLibrary(items);
      setLibraryOffset(offset);
      setHasMore(items.length === 10);
    } catch (reason) {
      fail(reason);
    }
  }
  async function renameLibraryItem(item: DatasetMetadata) {
    const name = window.prompt("Dataset name", item.name)?.trim();
    if (!name) return;
    try {
      await renameDataset(item.id, name);
      await searchLibrary(libraryOffset);
    } catch (reason) {
      fail(reason);
    }
  }
  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!dataset || !question.trim()) return;
    setBusy(true);
    setError("");
    try {
      const response = await askDataset(dataset.id, question, sessionId);
      setAnswer(response);
      setSessionId(response.metadata?.session_id ?? sessionId);
    } catch (reason) {
      fail(reason);
    } finally {
      setBusy(false);
    }
  }
  async function chartSubmit(event: FormEvent) {
    event.preventDefault();
    if (!dataset || !chartQuestion.trim() || chartBusy) return;
    setChartBusy(true);
    setChartError("");
    try {
      setChart(
        await createChart(
          dataset.id,
          chartQuestion,
          chartType === "auto" ? undefined : chartType,
          chartTitle || undefined,
        ),
      );
    } catch (reason) {
      setChart(null);
      setChartError(
        reason instanceof Error ? reason.message : "Unable to generate chart.",
      );
    } finally {
      setChartBusy(false);
    }
  }
  function operation(): CleaningOperation {
    const noColumn = ["remove_duplicates", "remove_missing_rows"].includes(
      cleanType,
    );
    return {
      type: cleanType,
      ...(noColumn ? {} : { column: cleanColumn }),
      ...(cleanType === "fill_missing_value" ? { value: fillValue } : {}),
    };
  }
  async function previewClean() {
    if (!dataset) return;
    setBusy(true);
    setError("");
    try {
      const selected = operation();
      setCleanOperation(selected);
      setPreview(await previewCleaning(dataset.id, [selected]));
    } catch (reason) {
      fail(reason);
    } finally {
      setBusy(false);
    }
  }
  async function confirmClean() {
    if (!dataset || !cleanOperation) return;
    setBusy(true);
    try {
      const result = await applyCleaning(dataset.id, [cleanOperation]);
      setProfile(result.profile);
      setPreview(null);
      setCleanOperation(null);
      await refreshSupporting(dataset.id);
    } catch (reason) {
      fail(reason);
    } finally {
      setBusy(false);
    }
  }
  async function reset() {
    if (!dataset) return;
    setBusy(true);
    try {
      setProfile(await resetDataset(dataset.id));
      await refreshSupporting(dataset.id);
      setPreview(null);
    } catch (reason) {
      fail(reason);
    } finally {
      setBusy(false);
    }
  }
  async function restore(version: number) {
    if (
      !dataset ||
      !window.confirm(`Restore version ${version} as a new working version?`)
    )
      return;
    setBusy(true);
    try {
      const result = await restoreVersion(dataset.id, version);
      setProfile(result.profile);
      await refreshSupporting(dataset.id);
    } catch (reason) {
      fail(reason);
    } finally {
      setBusy(false);
    }
  }
  async function buildReport() {
    if (!dataset) return;
    setReportBusy(true);
    setError("");
    setJob(null);
    try {
      const accepted = await createReportJob(dataset.id, reportOptions);
      for (let attempt = 0; attempt < 120; attempt += 1) {
        const current = await getJob(accepted.job_id);
        setJob(current);
        if (["completed", "failed", "cancelled"].includes(current.status))
          break;
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
    } catch (reason) {
      fail(reason);
    } finally {
      setReportBusy(false);
    }
  }
  async function saveCurrentAnalysis() {
    if (!dataset || !answer || !savedName.trim()) return;
    try {
      await saveAnalysis(
        dataset.id,
        savedName,
        answer.plan,
        answer.chart_suggestion
          ? { type: answer.chart_suggestion.type }
          : undefined,
      );
      setSavedName("");
      setSavedAnalyses(await listSavedAnalyses(dataset.id));
    } catch (reason) {
      fail(reason);
    }
  }
  async function rerunSaved(item: SavedAnalysis) {
    try {
      const result = await runSavedAnalysis(item.id);
      setAnswer({
        question: item.name,
        answer:
          "Saved analysis recalculated against the current dataset version.",
        plan: result.plan,
        result: result.result,
      });
      setActive("Ask Data");
    } catch (reason) {
      fail(reason);
    }
  }
  async function chartDrill(row: Record<string, string | number | null>) {
    if (!dataset || !chart || !nextDimension || row[chart.x_axis] == null)
      return;
    try {
      const result = await drillDown(
        dataset.id,
        chart.plan,
        chart.x_axis,
        row[chart.x_axis],
        nextDimension,
        breadcrumb,
      );
      setBreadcrumb(result.breadcrumb);
      setChart({
        ...chart,
        x_axis: nextDimension,
        data: result.result,
        plan: result.plan,
        title: `${chart.title} · ${result.breadcrumb.join(" › ")}`,
      });
    } catch (reason) {
      fail(reason);
    }
  }

  if (auth.loading || !auth.user)
    return <div className="page-loader">Preparing your workspace…</div>;
  const navigate = (tab: Tab) => {
    setActive(tab);
    setMobileNavOpen(false);
  };
  return (
    <main className={mobileNavOpen ? "nav-open" : ""}>
      <button
        className="mobile-menu"
        aria-label={mobileNavOpen ? "Close navigation" : "Open navigation"}
        aria-expanded={mobileNavOpen}
        onClick={() => setMobileNavOpen((value) => !value)}
      >
        ☰
      </button>
      <aside>
        <div className="brand">
          <span>DP</span>
          <div>
            DataPilot <b>AI</b>
          </div>
        </div>
        <nav aria-label="Main navigation">
          <p>Workspace</p>
          <button
            className={!dataset ? "active" : ""}
            onClick={() => {
              setDataset(null);
              setProfile(null);
              setMobileNavOpen(false);
            }}
          >
            Overview
          </button>
          <button
            className={!dataset ? "" : "active-context"}
            onClick={() => {
              if (dataset) navigate("Overview");
            }}
          >
            Datasets
          </button>
          {dataset && (
            <>
              <p>Analyze</p>
              {(["Ask Data", "Insights", "Charts"] as Tab[]).map((item) => (
                <button
                  className={item === active ? "active" : ""}
                  onClick={() => navigate(item)}
                  key={item}
                >
                  {item}
                </button>
              ))}
              <p>Prepare</p>
              {(["Data Quality", "Clean", "Versions"] as Tab[]).map((item) => (
                <button
                  className={item === active ? "active" : ""}
                  onClick={() => navigate(item)}
                  key={item}
                >
                  {item}
                </button>
              ))}
              <p>Work</p>
              {(["Saved Analyses", "Reports", "Export"] as Tab[]).map(
                (item) => (
                  <button
                    className={item === active ? "active" : ""}
                    onClick={() => navigate(item)}
                    key={item}
                  >
                    {item}
                  </button>
                ),
              )}
            </>
          )}
          <p>Workspace</p>
          <Link href="/history">Activity</Link>
          <Link href="/settings">Settings</Link>
          <Link href="/pricing">Plans</Link>
          <p>Support</p>
          <Link href="/feedback">Send Feedback</Link>
        </nav>
        <div className="status">
          <i /> {auth.workspace?.plan_code ?? "free"} plan
          <br />
          <small>Workspace isolated</small>
        </div>
      </aside>
      <section className="content">
        <header>
          <div>
            <p className="eyebrow">{auth.workspace?.name ?? "WORKSPACE"}</p>
            <h1>{dataset ? active : "Upload your data"}</h1>
            <p>
              {dataset
                ? `${dataset.name} · Current dataset`
                : "Turn spreadsheets into clear, calculated answers."}
            </p>
          </div>
          <div className="account-tools">
            <NotificationBell />
            <select
              aria-label="Current workspace"
              value={auth.workspace?.id ?? ""}
              onChange={(event) => {
                auth.selectWorkspace(event.target.value);
                setDataset(null);
                setProfile(null);
              }}
            >
              {auth.workspaces.map((workspace) => (
                <option value={workspace.id} key={workspace.id}>
                  {workspace.name}
                </option>
              ))}
            </select>
            <button
              className="avatar"
              aria-label="Sign out"
              title="Sign out"
              onClick={() => auth.logout().then(() => router.replace("/login"))}
            >
              {auth.user.display_name
                .split(/\s+/)
                .map((part) => part[0])
                .join("")
                .slice(0, 2)
                .toUpperCase()}
            </button>
          </div>
        </header>
        {dataset && (
          <nav className="breadcrumbs" aria-label="Breadcrumb">
            <button
              onClick={() => {
                setDataset(null);
                setProfile(null);
              }}
            >
              Datasets
            </button>
            <span>/</span>
            <button onClick={() => setActive("Overview")}>
              {dataset.name}
            </button>
            <span>/</span>
            <b>{active}</b>
          </nav>
        )}
        {!dataset && (
          <>
            {onboarding && !onboarding.dismissed && !onboarding.complete && (
              <section
                className="onboarding-card"
                aria-labelledby="onboarding-title"
              >
                <div>
                  <p className="eyebrow">
                    GET STARTED · {onboarding.completed}/{onboarding.total}
                  </p>
                  <h2 id="onboarding-title">Your first useful result</h2>
                  <p>{onboarding.welcome}</p>
                </div>
                <ol>
                  {onboarding.steps.map((step) => (
                    <li
                      className={step.complete ? "complete" : ""}
                      key={step.key}
                    >
                      <span>{step.complete ? "✓" : "○"}</span>
                      {step.label}
                    </li>
                  ))}
                </ol>
                <button className="secondary" onClick={dismissGuide}>
                  Dismiss guide
                </button>
              </section>
            )}
            {dashboard && (
              <div className="metrics">
                <article>
                  <span>Datasets</span>
                  <strong>{dashboard.usage.datasets}</strong>
                  <small>of {dashboard.usage.limits.datasets}</small>
                </article>
                <article>
                  <span>Storage</span>
                  <strong>
                    {(dashboard.usage.storage_bytes / 1048576).toFixed(1)} MB
                  </strong>
                  <small>{dashboard.usage.percentages.storage}% used</small>
                </article>
                <article>
                  <span>Analyses</span>
                  <strong>{dashboard.usage.analyses_this_month}</strong>
                  <small>this month</small>
                </article>
                <article>
                  <span>Reports</span>
                  <strong>{dashboard.usage.reports_this_month}</strong>
                  <small>{dashboard.usage.plan_code} plan</small>
                </article>
              </div>
            )}
            <div className="upload-card">
              <div className="upload-copy">
                <span className="icon">↥</span>
                <h2>Upload your first Excel or CSV file</h2>
                <p>
                  Your file is profiled, normalized to versioned Parquet, and
                  kept private to this workspace.
                </p>
              </div>
              <form onSubmit={upload}>
                <label className="dropzone">
                  <input
                    type="file"
                    accept=".csv,.xlsx,.xls"
                    onChange={(event) =>
                      chooseFile(event.target.files?.[0] ?? null)
                    }
                  />
                  <b>{file ? file.name : "Choose a file or drop it here"}</b>
                  <span>CSV, XLSX or XLS · up to 25 MB</span>
                </label>
                {sheets.length > 0 && (
                  <label className="field">
                    Worksheet
                    <select
                      value={sheet}
                      onChange={(event) => setSheet(event.target.value)}
                    >
                      {sheets.map((name) => (
                        <option key={name}>{name}</option>
                      ))}
                    </select>
                  </label>
                )}
                <button disabled={!file || busy}>
                  {busy ? "Analyzing…" : "Upload & analyze"}
                </button>
                <button
                  className="secondary"
                  type="button"
                  disabled={busy}
                  onClick={trySample}
                >
                  Try a sample dataset
                </button>
              </form>
            </div>
            <article className="panel workspace-panel">
              <p className="eyebrow">DATASET LIBRARY</p>
              <h2>Continue an analysis</h2>
              <div className="library-filters">
                <input
                  placeholder="Search by name"
                  value={librarySearch}
                  onChange={(e) => setLibrarySearch(e.target.value)}
                />
                <select
                  value={libraryType}
                  onChange={(e) => setLibraryType(e.target.value)}
                >
                  <option value="">All file types</option>
                  <option value="csv">CSV</option>
                  <option value="excel">Excel</option>
                </select>
                <label>
                  <input
                    type="checkbox"
                    checked={recentlyAnalyzed}
                    onChange={(e) => setRecentlyAnalyzed(e.target.checked)}
                  />{" "}
                  Recently analyzed
                </label>
                <button onClick={() => searchLibrary(0)}>Apply</button>
              </div>
              <div className="version-list">
                {library.map((item) => (
                  <div key={item.id}>
                    <span>
                      {item.source_type?.toUpperCase() ??
                        `v${item.current_version ?? 0}`}
                    </span>
                    <div>
                      <h3>{item.name}</h3>
                      <p>
                        {item.rows.toLocaleString()} rows · {item.columns}{" "}
                        columns · uploaded{" "}
                        {new Date(item.created_at).toLocaleDateString()}
                        {item.last_analyzed_at
                          ? ` · analyzed ${new Date(item.last_analyzed_at).toLocaleDateString()}`
                          : ""}
                      </p>
                    </div>
                    <button
                      className="secondary"
                      onClick={() => openDataset(item.id)}
                    >
                      Open
                    </button>
                    <button
                      className="secondary"
                      onClick={() => renameLibraryItem(item)}
                    >
                      Rename
                    </button>
                    <button
                      className="danger"
                      onClick={() => removeDataset(item.id)}
                    >
                      Delete
                    </button>
                  </div>
                ))}
                {!library.length && (
                  <div className="empty-state">
                    No matching datasets. Upload your first Excel or CSV file.
                  </div>
                )}
              </div>
              <div className="pagination">
                <button
                  className="secondary"
                  disabled={libraryOffset === 0}
                  onClick={() => searchLibrary(Math.max(0, libraryOffset - 10))}
                >
                  Previous
                </button>
                <span>
                  {libraryOffset + 1}–{libraryOffset + library.length}
                </span>
                <button
                  className="secondary"
                  disabled={!hasMore}
                  onClick={() => searchLibrary(libraryOffset + 10)}
                >
                  Next
                </button>
              </div>
            </article>
          </>
        )}
        {error && (
          <div className="error">
            <span>{error}{planLimit&&<> <Link href="/pricing">View plans</Link></>}</span>
            <button onClick={() => {setError("");setPlanLimit(false);}}>×</button>
          </div>
        )}
        {dataset && profile && (
          <>
            <div className="metrics">
              <article>
                <span>Rows</span>
                <strong>{format(profile.row_count)}</strong>
                <small>working records</small>
              </article>
              <article>
                <span>Columns</span>
                <strong>{profile.column_count}</strong>
                <small>{profile.numeric_columns.length} numeric</small>
              </article>
              <article>
                <span>Missing</span>
                <strong>{format(profile.missing_values)}</strong>
                <small>empty cells</small>
              </article>
              <article>
                <span>Duplicates</span>
                <strong>{format(profile.duplicate_rows)}</strong>
                <small>matching rows</small>
              </article>
            </div>
            <div className="tabs">
              {tabs.map((tab) => (
                <button
                  className={active === tab ? "selected" : ""}
                  onClick={() => setActive(tab)}
                  key={tab}
                >
                  {tab}
                </button>
              ))}
            </div>
            {active === "Overview" && (
              <article className="panel">
                <div className="panel-title">
                  <div>
                    <p className="eyebrow">DATASET PROFILE</p>
                    <h2>Columns at a glance</h2>
                  </div>
                  <button
                    className="secondary"
                    onClick={() => {
                      setDataset(null);
                      setProfile(null);
                      setFile(null);
                    }}
                  >
                    New upload
                  </button>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Column</th>
                        <th>Type</th>
                        <th>Unique</th>
                        <th>Missing</th>
                        <th>Summary</th>
                      </tr>
                    </thead>
                    <tbody>
                      {profile.columns.map((column) => (
                        <tr key={column.name}>
                          <td>
                            <b>{column.name}</b>
                          </td>
                          <td>
                            <em className={`pill ${column.category}`}>
                              {column.category}
                            </em>
                          </td>
                          <td>{format(column.unique_count)}</td>
                          <td>{column.missing_percentage}%</td>
                          <td>
                            {column.semantic_role === "measure"
                              ? `Σ ${column.sum?.toLocaleString() ?? "—"}`
                              : column.minimum
                                ? `${String(column.minimum).slice(0, 10)} → ${String(column.maximum).slice(0, 10)}`
                                : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <details>
                  <summary>Technical semantic profile</summary>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Column</th>
                          <th>Physical type</th>
                          <th>Semantic role</th>
                          <th>Confidence</th>
                          <th>Allowed aggregations</th>
                        </tr>
                      </thead>
                      <tbody>
                        {profile.columns.map((column) => (
                          <tr key={column.name}>
                            <td>{column.name}</td>
                            <td>{column.physical_type}</td>
                            <td>{column.semantic_role.replaceAll("_", " ")}</td>
                            <td>{Math.round(column.confidence * 100)}%</td>
                            <td>{column.allowed_aggregations.join(", ")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              </article>
            )}
            {active === "Ask Data" && (
              <article className="panel workspace-panel">
                <p className="eyebrow">ASK YOUR DATA</p>
                <h2>What would you like to know?</h2>
                <p>
                  Plans are interpreted locally; calculations always run against
                  your dataset. This session is saved automatically.
                </p>
                {questionExamples.length > 0 && (
                  <div
                    className="question-examples"
                    aria-label="Suggested questions"
                  >
                    {questionExamples.map((example) => (
                      <button
                        type="button"
                        className="secondary"
                        key={example}
                        onClick={() => setQuestion(example)}
                      >
                        {example}
                      </button>
                    ))}
                  </div>
                )}
                <form className="action-form" onSubmit={ask}>
                  <textarea
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    placeholder="Try “Show each region's contribution to total sales”"
                  />
                  <button disabled={busy || !question.trim()}>
                    Ask DataPilot
                  </button>
                </form>
                {answer && (
                  <div className="answer">
                    <span>CALCULATED ANSWER</span>
                    <h3>{answer.answer}</h3>
                    <div className="first-success">
                      You’ve completed a successful analysis. Review the
                      interpretation below, then chart, save, or export it.
                    </div>
                    {answer.metadata?.interpreted_as && (
                      <p>
                        <b>Interpreted as:</b> {answer.metadata.interpreted_as}
                      </p>
                    )}
                    {answer.explanation && (
                      <div className="calculation-trace">
                        <b>Calculated using</b>
                        <small>
                          {answer.explanation.metric || "Rows"} →{" "}
                          {answer.explanation.aggregation || "Calculation"}
                          {answer.explanation.grouped_by?.length
                            ? ` · Grouped by ${answer.explanation.grouped_by.join(", ")}`
                            : ""}
                          {answer.explanation.filters?.length
                            ? ` · ${answer.explanation.filters.length} filter(s)`
                            : ""}
                        </small>
                      </div>
                    )}
                    {answer.metadata && (
                      <p className="technical-meta">
                        Dataset version {answer.metadata.dataset_version} ·{" "}
                        {answer.metadata.execution_ms} ms
                        {answer.metadata.provider_fallback
                          ? " · Local fallback used"
                          : ""}
                        {answer.metadata.cached ? " · Cached" : ""}
                      </p>
                    )}
                    <details>
                      <summary>View analysis plan and result</summary>
                      <pre>
                        {JSON.stringify(
                          { plan: answer.plan, result: answer.result },
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                    <div className="clean-form">
                      <input
                        value={savedName}
                        onChange={(event) => setSavedName(event.target.value)}
                        placeholder="Saved analysis name"
                      />
                      <button
                        className="secondary"
                        disabled={!savedName.trim()}
                        onClick={saveCurrentAnalysis}
                      >
                        Save analysis
                      </button>
                      {answer.chart_suggestion && (
                        <button
                          className="secondary"
                          onClick={() => {
                            setChartQuestion(question);
                            setChartType("auto");
                            setActive("Charts");
                          }}
                        >
                          Create suggested chart
                        </button>
                      )}
                    </div>
                    <div className="result-rating">
                      <span>Was this result useful?</span>
                      <button
                        className={
                          resultRating === "yes"
                            ? "selected secondary"
                            : "secondary"
                        }
                        disabled={!answer.metadata?.run_id}
                        onClick={() => rateCurrent(true)}
                      >
                        Yes
                      </button>
                      <button
                        className={
                          resultRating === "no"
                            ? "selected secondary"
                            : "secondary"
                        }
                        disabled={!answer.metadata?.run_id}
                        onClick={() => rateCurrent(false)}
                      >
                        Not yet
                      </button>
                      {resultRating && (
                        <small>
                          Thanks — your rating helps us improve the beta.
                        </small>
                      )}
                    </div>
                  </div>
                )}
              </article>
            )}
            {active === "Insights" && (
              <section>
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">AUTOMATIC INSIGHTS</p>
                    <h2>Findings calculated from your data</h2>
                  </div>
                </div>
                <div className="card-grid">
                  {insights.map((item, index) => (
                    <article
                      className={`insight-card ${item.severity}`}
                      key={`${item.title}-${index}`}
                    >
                      <span>{item.type.replaceAll("_", " ")}</span>
                      <h3>{item.title}</h3>
                      <p>{item.description}</p>
                      {item.value !== null && item.value !== undefined && (
                        <strong>
                          {typeof item.value === "number"
                            ? item.value.toLocaleString()
                            : item.value}
                        </strong>
                      )}
                    </article>
                  ))}
                  {!insights.length && (
                    <div className="empty-state">
                      No notable insights were detected.
                    </div>
                  )}
                </div>
              </section>
            )}
            {active === "Charts" && (
              <article className="panel workspace-panel">
                <p className="eyebrow">CHART BUILDER</p>
                <h2>Visualize calculated results</h2>
                <p>
                  Describe the result you want to compare. Rankings with long
                  labels use readable horizontal bars automatically.
                </p>
                <form className="chart-form" onSubmit={chartSubmit}>
                  <label>
                    Question
                    <input
                      value={chartQuestion}
                      onChange={(event) => setChartQuestion(event.target.value)}
                      placeholder="Show top 5 car names by average selling price"
                    />
                  </label>
                  <label>
                    Optional title
                    <input
                      value={chartTitle}
                      onChange={(event) => setChartTitle(event.target.value)}
                      placeholder="Top cars by price"
                    />
                  </label>
                  <label>
                    Chart type
                    <select
                      value={chartType}
                      onChange={(event) =>
                        setChartType(event.target.value as ChartType | "auto")
                      }
                    >
                      <option value="auto">Auto (recommended)</option>
                      {["bar", "column", "line", "pie", "scatter"].map(
                        (type) => (
                          <option key={type}>{type}</option>
                        ),
                      )}
                    </select>
                  </label>
                  <button disabled={chartBusy || !chartQuestion.trim()}>
                    {chartBusy ? "Generating…" : "Generate chart"}
                  </button>
                </form>
                {chartBusy && (
                  <div className="chart-loading" role="status">
                    <i />
                    Calculating chart data and choosing a readable layout…
                  </div>
                )}
                {chartError && (
                  <div className="chart-error" role="alert">
                    <h3>Unable to generate chart.</h3>
                    <p>{chartError}</p>
                    <button
                      className="secondary"
                      onClick={() => {
                        setChartError("");
                        setChartType("auto");
                      }}
                    >
                      Try automatic chart type
                    </button>
                  </div>
                )}
                {chart && !chartBusy && (
                  <>
                    <div className="chart-heading">
                      <div>
                        <h3>{chart.title}</h3>
                        <p>
                          <b>Interpreted as:</b>{" "}
                          {chart.interpretation.interpreted_as}
                        </p>
                        {chart.selected_chart_type !==
                          chart.recommended_chart_type && (
                          <p className="technical-meta">
                            Recommended: {chart.recommended_chart_type}
                          </p>
                        )}
                        {breadcrumb.length > 0 && (
                          <p className="technical-meta">
                            {breadcrumb.join(" › ")}
                          </p>
                        )}
                      </div>
                      <em>
                        {chart.type === "bar" ? "horizontal bar" : chart.type}
                      </em>
                    </div>
                    {profile.categorical_columns.some(
                      (name) => name !== chart.x_axis,
                    ) && (
                      <label className="field">
                        Drill into
                        <select
                          value={nextDimension}
                          onChange={(event) =>
                            setNextDimension(event.target.value)
                          }
                        >
                          {profile.categorical_columns
                            .filter((name) => name !== chart.x_axis)
                            .map((name) => (
                              <option key={name}>{name}</option>
                            ))}
                        </select>
                      </label>
                    )}
                    <DataChart chart={chart} onPointClick={chartDrill} />
                    {nextDimension && (
                      <p className="technical-meta">
                        Select a bar or point to filter by its full category
                        value and group by the selected dimension.
                      </p>
                    )}
                    <details>
                      <summary>View underlying chart data</summary>
                      <pre>{JSON.stringify(chart.data, null, 2)}</pre>
                    </details>
                  </>
                )}
              </article>
            )}
            {active === "Data Quality" && (
              <section>
                <p className="eyebrow">DATA QUALITY</p>
                <h2>Issues worth reviewing</h2>
                <div className="quality-list">
                  {quality.map((item, index) => (
                    <article
                      className="quality-item"
                      key={`${item.issue_type}-${item.column}-${index}`}
                    >
                      <span className={`severity ${item.severity}`} />
                      <div>
                        <h3>{item.issue_type.replaceAll("_", " ")}</h3>
                        <p>
                          {item.column ? `${item.column} · ` : ""}
                          {item.count.toLocaleString()} affected ·{" "}
                          {item.confidence} confidence
                        </p>
                        {item.message && <p>{item.message}</p>}
                        {item.examples.length > 0 && (
                          <code>{item.examples.join(" · ")}</code>
                        )}
                      </div>
                    </article>
                  ))}
                  {!quality.length && (
                    <div className="empty-state success">
                      No quality issues detected.
                    </div>
                  )}
                </div>
              </section>
            )}
            {active === "Clean" && (
              <article className="panel workspace-panel">
                <p className="eyebrow">PREVIEW-FIRST CLEANING</p>
                <h2>Clean the working dataset safely</h2>
                <p>
                  The original upload is preserved and can always be restored.
                </p>
                <div className="clean-form">
                  <label>
                    Operation
                    <select
                      value={cleanType}
                      onChange={(event) => {
                        setCleanType(event.target.value as CleaningType);
                        setPreview(null);
                      }}
                    >
                      {[
                        "trim_whitespace",
                        "standardize_lowercase",
                        "standardize_uppercase",
                        "standardize_titlecase",
                        "remove_duplicates",
                        "remove_missing_rows",
                        "fill_missing_mean",
                        "fill_missing_median",
                        "fill_missing_value",
                      ].map((type) => (
                        <option key={type} value={type}>
                          {type.replaceAll("_", " ")}
                        </option>
                      ))}
                    </select>
                  </label>
                  {!["remove_duplicates", "remove_missing_rows"].includes(
                    cleanType,
                  ) && (
                    <label>
                      Column
                      <select
                        value={cleanColumn}
                        onChange={(event) => setCleanColumn(event.target.value)}
                      >
                        {profile.columns.map((column) => (
                          <option key={column.name}>{column.name}</option>
                        ))}
                      </select>
                    </label>
                  )}
                  {cleanType === "fill_missing_value" && (
                    <label>
                      Fill value
                      <input
                        value={fillValue}
                        onChange={(event) => setFillValue(event.target.value)}
                      />
                    </label>
                  )}
                  <button onClick={previewClean} disabled={busy}>
                    Preview changes
                  </button>
                  <button className="secondary" onClick={reset} disabled={busy}>
                    Reset to original
                  </button>
                </div>
                {preview && (
                  <div className="clean-preview">
                    <h3>Confirm these changes</h3>
                    <p>
                      <b>{preview.affected_rows.toLocaleString()}</b> rows and{" "}
                      <b>{preview.affected_cells.toLocaleString()}</b> cells
                      affected. Result:{" "}
                      {preview.resulting_rows.toLocaleString()} rows.
                    </p>
                    {preview.changes.map((change, index) => (
                      <div key={index}>
                        <strong>
                          {change.operation.type.replaceAll("_", " ")}
                        </strong>
                        <small>
                          Before: {change.before_examples.join(" · ") || "—"}
                          <br />
                          After: {change.after_examples.join(" · ") || "—"}
                        </small>
                      </div>
                    ))}
                    <button
                      className="danger"
                      onClick={confirmClean}
                      disabled={busy}
                    >
                      Confirm and apply
                    </button>
                    <button
                      className="secondary"
                      onClick={() => setPreview(null)}
                    >
                      Cancel
                    </button>
                  </div>
                )}
              </article>
            )}
            {active === "Versions" && (
              <article className="panel workspace-panel">
                <p className="eyebrow">VERSION HISTORY</p>
                <h2>Immutable dataset checkpoints</h2>
                <p>
                  Every confirmed cleaning or restore creates a new version.
                  Version 0 always remains the original upload.
                </p>
                <div className="version-list">
                  {versions
                    .slice()
                    .reverse()
                    .map((version) => (
                      <div key={version.version}>
                        <span
                          className={
                            version.is_current ? "version-current" : ""
                          }
                        >
                          v{version.version}
                          {version.is_current ? " · current" : ""}
                        </span>
                        <div>
                          <h3>{version.description}</h3>
                          <p>
                            {new Date(version.created_at).toLocaleString()} ·
                            Affected Rows:{" "}
                            {version.affected_rows.toLocaleString()}
                          </p>
                        </div>
                        <button
                          className="secondary"
                          disabled={version.is_current || busy}
                          onClick={() => restore(version.version)}
                        >
                          Restore
                        </button>
                      </div>
                    ))}
                </div>
              </article>
            )}
            {active === "Saved Analyses" && (
              <article className="panel workspace-panel">
                <p className="eyebrow">SAVED ANALYSES</p>
                <h2>Reusable query plans</h2>
                <p>
                  Reruns are validated and calculated against the current
                  dataset version.
                </p>
                <div className="version-list">
                  {savedAnalyses.map((item) => (
                    <div key={item.id}>
                      <span>QUERY</span>
                      <div>
                        <h3>{item.name}</h3>
                        <p>
                          Updated {new Date(item.updated_at).toLocaleString()}
                        </p>
                      </div>
                      <button
                        className="secondary"
                        onClick={() => rerunSaved(item)}
                      >
                        Run
                      </button>
                      <button
                        className="danger"
                        onClick={async () => {
                          await deleteSavedAnalysis(item.id);
                          setSavedAnalyses(await listSavedAnalyses(dataset.id));
                        }}
                      >
                        Delete
                      </button>
                    </div>
                  ))}
                  {!savedAnalyses.length && (
                    <div className="empty-state">
                      Save a result from Ask Data to reuse it here.
                    </div>
                  )}
                </div>
              </article>
            )}
            {active === "Reports" && (
              <article className="panel workspace-panel">
                <p className="eyebrow">ANALYSIS REPORT</p>
                <h2>Generate a persistent report job</h2>
                <div className="report-options">
                  <label>
                    Report title
                    <input
                      value={reportOptions.title}
                      onChange={(event) =>
                        setReportOptions({
                          ...reportOptions,
                          title: event.target.value,
                        })
                      }
                    />
                  </label>
                  <label>
                    Format
                    <select
                      value={reportOptions.format}
                      onChange={(event) =>
                        setReportOptions({
                          ...reportOptions,
                          format: event.target.value as "html" | "pdf",
                        })
                      }
                    >
                      <option value="pdf">PDF</option>
                      <option value="html">HTML</option>
                    </select>
                  </label>
                  {(
                    [
                      "include_profile",
                      "include_insights",
                      "include_quality",
                      "include_charts",
                      "include_version_history",
                    ] as const
                  ).map((key) => (
                    <label className="check" key={key}>
                      <input
                        type="checkbox"
                        checked={reportOptions[key]}
                        onChange={(event) =>
                          setReportOptions({
                            ...reportOptions,
                            [key]: event.target.checked,
                          })
                        }
                      />
                      {key.replace("include_", "").replaceAll("_", " ")}
                    </label>
                  ))}
                  <button
                    disabled={reportBusy || !reportOptions.title.trim()}
                    onClick={buildReport}
                  >
                    {reportBusy
                      ? `${job?.stage ?? "Queued"} · ${job?.progress ?? 0}%`
                      : "Generate report"}
                  </button>
                  {job?.status === "completed" && (
                    <button
                      className="secondary"
                      onClick={() => downloadJobResult(job)}
                    >
                      Download {reportOptions.format.toUpperCase()}
                    </button>
                  )}
                </div>
                {job && (
                  <div className="answer">
                    <span>JOB {job.status.toUpperCase()}</span>
                    <h3>{job.stage}</h3>
                    <p>{job.progress ?? 0}% complete</p>
                    {job.error_message && (
                      <p className="error">{job.error_message}</p>
                    )}
                  </div>
                )}
              </article>
            )}
            {active === "Export" && (
              <article className="panel workspace-panel">
                <p className="eyebrow">EXPORT</p>
                <h2>Download your data</h2>
                <p>
                  Export the current cleaned version or the untouched original
                  upload.
                </p>
                <div className="export-grid">
                  {(["current", "original"] as const).map((version) => (
                    <div key={version}>
                      <h3>
                        {version === "current"
                          ? "Current working data"
                          : "Original upload"}
                      </h3>
                      <p>
                        {version === "current"
                          ? "Includes confirmed cleaning changes."
                          : "Preserved exactly as initially parsed."}
                      </p>
                      <button
                        onClick={() =>
                          downloadExport(dataset.id, "csv", version)
                        }
                      >
                        Export CSV
                      </button>
                      <button
                        className="secondary"
                        onClick={() =>
                          downloadExport(dataset.id, "xlsx", version)
                        }
                      >
                        Export Excel
                      </button>
                    </div>
                  ))}
                </div>
              </article>
            )}
          </>
        )}
      </section>
    </main>
  );
}
