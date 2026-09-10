import { useEffect, useState } from "react";
import { api } from "../client";
import { Badge, Card, Empty, ErrorBox, PageTitle, Spinner, cn } from "../components/ui";

export default function RulesReference() {
  const [rules, setRules] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    api.get("/rules")
      .then((d) => setRules(d.items))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (error) return <ErrorBox error={error} />;

  const shown = rules.filter((r) => {
    if (filter && r.status !== filter) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        (r.rule_number || "").toLowerCase().includes(q) ||
        (r.sub_rule || "").toLowerCase().includes(q) ||
        (r.title || "").toLowerCase().includes(q) ||
        (r.requirement || "").toLowerCase().includes(q)
      );
    }
    return true;
  });

  return (
    <div>
      <PageTitle
        title="Rules & Standards"
        subtitle={`Reference view of the versioned rule engine — ${rules.length} rules loaded from the Legal Metrology (Packaged Commodities) Rules, 2011.`}
      />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {["", "active", "historical", "future", "superseded", "draft"].map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={cn(
              "rounded-lg px-3 py-1.5 text-xs font-bold transition-colors",
              filter === s ? "bg-navy-700 text-white" : "bg-white text-slate-600 border border-slate-200 hover:border-navy-400"
            )}
          >
            {s ? s.toUpperCase() : `ALL (${rules.length})`}
          </button>
        ))}
        <input
          className="ml-auto max-w-xs rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          placeholder="🔍 Search rule number, title…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {loading ? (
        <Spinner label="Loading rules…" />
      ) : shown.length === 0 ? (
        <Empty icon="⚖️" text={search || filter ? "No rules match the current filter." : "No rules in database."} />
      ) : (
        <>
          <div className="mb-2 text-xs text-slate-400">{shown.length} rule{shown.length !== 1 ? "s" : ""} shown</div>
          <div className="grid gap-3 lg:grid-cols-2">
            {shown.map((r) => (
              <Card key={r.id} className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-sm font-extrabold text-navy-800">
                      {r.rule_number ? `Rule ${r.rule_number}` : ""}{r.sub_rule ? ` — ${r.sub_rule}` : ""}
                    </div>
                    <div className="text-xs font-semibold text-slate-500">{r.title}</div>
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-1">
                    <Badge value={r.status} />
                    <Badge value={r.type} />
                    {r.severity && <Badge value={r.severity} />}
                  </div>
                </div>
                {r.requirement && <p className="mt-2 text-xs text-slate-700">{r.requirement}</p>}
                {r.description && <p className="mt-1 text-[11px] text-slate-400">{r.description}</p>}
                <div className="mt-2 flex flex-wrap items-center gap-3 text-[10px] text-slate-400">
                  <span>Effective {r.effective_from}{r.effective_to ? ` → ${r.effective_to}` : " (in force)"}</span>
                  <span>· v{r.version}</span>
                  {r.source && <span>· {r.source}</span>}
                  {r.scope && r.scope !== "image_checkable" && (
                    <span className={cn(
                      "rounded px-1.5 py-0.5 font-bold",
                      r.scope === "reference" ? "bg-slate-100 text-slate-500" :
                      r.scope === "manual_review" ? "bg-amber-100 text-amber-700" :
                      "bg-blue-50 text-blue-600"
                    )}>
                      {r.scope}
                    </span>
                  )}
                </div>
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
