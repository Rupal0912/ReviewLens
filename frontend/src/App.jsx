import { useEffect, useMemo, useState } from "react";
import { getLatest, suggestReply, uploadCsv } from "./api.js";

const SENTIMENT_STYLE = {
  positive: { bar: "bg-pos", text: "text-pos", label: "Positive" },
  neutral: { bar: "bg-neu", text: "text-neu", label: "Neutral" },
  negative: { bar: "bg-neg", text: "text-neg", label: "Negative" },
};
const topicName = (t) => t.replace("_", " ");

function Upload({ onFile, busy }) {
  return (
    <label className={`inline-flex items-center gap-3 rounded border border-line bg-white px-4 py-2 text-sm font-medium cursor-pointer hover:border-accent ${busy ? "opacity-60 pointer-events-none" : ""}`}>
      <span>{busy ? "Analysing reviews…" : "Upload reviews.csv"}</span>
      <input type="file" accept=".csv,text/csv" className="sr-only"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }} />
    </label>
  );
}

function SentimentBar({ stats }) {
  const order = ["positive", "neutral", "negative"];
  return (
    <section aria-label="Sentiment split">
      <div className="flex h-10 w-full overflow-hidden rounded" role="img"
        aria-label={order.map((s) => `${stats.percentages[s]}% ${s}`).join(", ")}>
        {order.map((s) => stats.percentages[s] > 0 && (
          <div key={s} className={SENTIMENT_STYLE[s].bar} style={{ width: `${stats.percentages[s]}%` }} />
        ))}
      </div>
      <dl className="mt-3 flex flex-wrap gap-x-10 gap-y-2">
        {order.map((s) => (
          <div key={s}>
            <dt className="text-sm text-muted">{SENTIMENT_STYLE[s].label}</dt>
            <dd className={`text-2xl font-semibold ${SENTIMENT_STYLE[s].text}`}>
              {stats.percentages[s]}% <span className="text-sm font-normal text-muted">({stats.sentiment[s]})</span>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function TopList({ title, items, tone }) {
  return (
    <section>
      <h2 className="text-base font-semibold">{title}</h2>
      {items.length === 0 ? <p className="mt-2 text-sm text-muted">Nothing to show yet.</p> : (
        <ol className="mt-2 divide-y divide-line border-y border-line">
          {items.map((it) => (
            <li key={it.topic} className="py-2">
              <div className="flex items-baseline justify-between">
                <span className={`font-medium capitalize ${tone}`}>{topicName(it.topic)}</span>
                <span className="text-sm text-muted">{it.count} {it.count === 1 ? "review" : "reviews"}</span>
              </div>
              <p className="text-sm text-muted">e.g. {it.example}</p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function Select({ label, value, onChange, options }) {
  return (
    <label className="text-sm text-muted">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className="ml-2 rounded border border-line bg-white px-2 py-1 text-ink">
        <option value="">All</option>
        {options.map((o) => <option key={o} value={o}>{topicName(o)}</option>)}
      </select>
    </label>
  );
}

function Status({ r }) {
  if (r.status === "skipped_empty") return <span className="text-muted">Skipped: empty review</span>;
  if (r.status === "analysis_failed") return <span className="text-neg">Analysis failed</span>;
  return null;
}

function ReviewRow({ r, onReply, replying }) {
  const s = r.sentiment && SENTIMENT_STYLE[r.sentiment];
  const notes = [];
  if (r.duplicate_of) notes.push(`Duplicate of ${r.duplicate_of}`);
  if (r.issues.includes("missing_rating")) notes.push("Rating missing");
  if (r.issues.includes("invalid_rating")) notes.push(`Invalid rating “${r.rating_raw}”`);
  if (r.mismatch) notes.push("Rating and text disagree");
  return (
    <tr className="align-top border-t border-line">
      <td className="py-3 pr-3 font-medium whitespace-nowrap">{r.review_id}</td>
      <td className="py-3 pr-3">{r.product}</td>
      <td className="py-3 pr-3 whitespace-nowrap">{r.rating ?? "–"}</td>
      <td className="py-3 pr-3 max-w-md">
        <p className="break-words">{r.text || <span className="text-muted">(no text)</span>}</p>
        {r.summary && <p className="mt-1 text-sm text-muted">{r.summary}</p>}
        {notes.length > 0 && <p className="mt-1 text-xs text-muted">{notes.join(" · ")}</p>}
        {r.suggested_reply && (
          <p className="mt-2 rounded border-l-4 border-accent bg-white px-3 py-2 text-sm">{r.suggested_reply}</p>
        )}
      </td>
      <td className="py-3 pr-3 whitespace-nowrap">
        {s ? <span className={`font-medium ${s.text}`}>{s.label}</span> : <Status r={r} />}
      </td>
      <td className="py-3 pr-3 capitalize">{r.topics.map(topicName).join(", ")}</td>
      <td className="py-3 whitespace-nowrap">
        {r.needs_reply && !r.suggested_reply && (
          <button onClick={() => onReply(r.id)} disabled={replying}
            className="rounded bg-accent px-3 py-1 text-sm font-medium text-white disabled:opacity-60">
            {replying ? "Writing…" : "Suggest reply"}
          </button>
        )}
        {r.needs_reply && r.suggested_reply && <span className="text-sm text-muted">Reply drafted</span>}
      </td>
    </tr>
  );
}

export default function App() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [replyingId, setReplyingId] = useState(null);
  const [filters, setFilters] = useState({ product: "", sentiment: "", topic: "" });

  useEffect(() => {
    getLatest().then(setData).catch((e) => { if (e.status !== 404) setError(e.message); });
  }, []);

  async function handleFile(file) {
    setBusy(true); setError("");
    try { setData(await uploadCsv(file)); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function handleReply(rowId) {
    setReplyingId(rowId); setError("");
    try {
      const { suggested_reply } = await suggestReply(rowId);
      setData((d) => ({ ...d, reviews: d.reviews.map((r) => (r.id === rowId ? { ...r, suggested_reply } : r)) }));
    } catch (e) { setError(e.message); }
    finally { setReplyingId(null); }
  }

  const rows = useMemo(() => (data?.reviews ?? []).filter((r) =>
    (!filters.product || r.product === filters.product) &&
    (!filters.sentiment || r.sentiment === filters.sentiment) &&
    (!filters.topic || r.topics.includes(filters.topic))), [data, filters]);

  const stats = data?.stats;
  return (
    <main className="mx-auto max-w-6xl px-5 py-8">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">ReviewLens</h1>
          <p className="text-muted">What customers are saying, and which reviews need an answer.</p>
        </div>
        <Upload onFile={handleFile} busy={busy} />
      </header>

      {error && <p role="alert" className="mt-4 rounded border border-neg bg-white px-4 py-2 text-neg">{error}</p>}

      {!data ? (
        <p className="mt-16 text-lg text-muted">Upload a CSV of product reviews to see sentiment, topics, complaints and praise.</p>
      ) : (
        <>
          <p className="mt-6 text-sm text-muted">
            {data.upload.filename}: {stats.analysed} of {stats.total_rows} rows analysed
            {stats.skipped > 0 && `, ${stats.skipped} skipped`}
            {stats.failed > 0 && `, ${stats.failed} failed`}
            {stats.duplicates > 0 && `, ${stats.duplicates} duplicate`}
          </p>
          <div className="mt-4 space-y-8">
            <SentimentBar stats={stats} />
            <div className="flex flex-wrap gap-x-10 gap-y-3">
              <div><div className="text-sm text-muted">Reviews needing a reply</div><div className="text-2xl font-semibold">{stats.needs_reply}</div></div>
              <div><div className="text-sm text-muted">Rating and text agree</div><div className="text-2xl font-semibold">{stats.agreement_pct ?? "–"}{stats.agreement_pct != null && "%"}</div></div>
              <div><div className="text-sm text-muted">AI calls / cache hits</div><div className="text-2xl font-semibold">{stats.run.ai_calls} / {stats.run.cache_hits}</div></div>
              <div><div className="text-sm text-muted">Processing time</div><div className="text-2xl font-semibold">{stats.run.seconds}s</div></div>
            </div>
            <div className="grid gap-8 md:grid-cols-2">
              <TopList title="Top complaints" items={stats.top_complaints} tone="text-neg" />
              <TopList title="Top praises" items={stats.top_praises} tone="text-pos" />
            </div>
            <section>
              <h2 className="text-base font-semibold">Topics mentioned</h2>
              <p className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm">
                {stats.topics.map((t) => <span key={t.topic}><span className="capitalize">{topicName(t.topic)}</span> <span className="text-muted">{t.count}</span></span>)}
              </p>
            </section>

            <section>
              <div className="flex flex-wrap items-center gap-4">
                <h2 className="text-base font-semibold">Reviews</h2>
                <Select label="Product" value={filters.product} onChange={(v) => setFilters({ ...filters, product: v })} options={data.products} />
                <Select label="Sentiment" value={filters.sentiment} onChange={(v) => setFilters({ ...filters, sentiment: v })} options={["positive", "neutral", "negative"]} />
                <Select label="Topic" value={filters.topic} onChange={(v) => setFilters({ ...filters, topic: v })} options={["quality", "delivery", "price", "packaging", "support", "size_fit", "other"]} />
                <span className="text-sm text-muted">{rows.length} shown</span>
              </div>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[820px] text-left text-sm">
                  <thead className="text-muted">
                    <tr><th className="pb-2 pr-3 font-medium">ID</th><th className="pb-2 pr-3 font-medium">Product</th><th className="pb-2 pr-3 font-medium">Stars</th><th className="pb-2 pr-3 font-medium">Review</th><th className="pb-2 pr-3 font-medium">Sentiment</th><th className="pb-2 pr-3 font-medium">Topics</th><th className="pb-2 font-medium">Reply</th></tr>
                  </thead>
                  <tbody>{rows.map((r) => <ReviewRow key={r.id} r={r} onReply={handleReply} replying={replyingId === r.id} />)}</tbody>
                </table>
              </div>
            </section>
          </div>
        </>
      )}
    </main>
  );
}
