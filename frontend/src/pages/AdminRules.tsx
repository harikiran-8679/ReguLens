import { useEffect, useState } from "react";
import { api } from "../client";
import { Badge, Button, Card, ErrorBox, Field, Modal, PageTitle, Spinner, Table, inputCls } from "../components/ui";

export default function AdminRules() {
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<any>(null); // editing rule or {__new:true}
  const [busy, setBusy] = useState(false);

  const load = () => {
    setLoading(true);
    return api.get(`/rules${filter ? `?status=${filter}` : ""}`)
      .then((d) => setItems(d.items))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      if (open.__new) {
        const { __new, id, rule_id, ...body } = open;
        await api.post("/admin/rules", body);
      } else {
        const { id, rule_id, ...body } = open;
        await api.patch(`/admin/rules/${id}`, body);
      }
      setOpen(null);
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const deactivate = async (r: any) => {
    if (!confirm(`Mark ${r.rule_id} as superseded? (history is preserved)`)) return;
    try {
      await api.del(`/admin/rules/${r.id}`);
      await load();
    } catch (e: any) {
      setError((e as any).message);
    }
  };

  const blank = {
    __new: true,
    rule_number: "Rule ", sub_rule: "", title: "", type: "content",
    category: "mandatory_declaration", requirement: "", description: "",
    field: "", required: true, applicability: ["*"], conditions: {},
    validation: { kind: "present", field: "" },
    severity: "major", evidence_required: true,
    effective_from: "2011-05-30", effective_to: "", version: 1,
    source: "", status: "draft",
  };

  return (
    <div>
      <PageTitle
        title="Rules & Standards"
        subtitle="Versioned rule-engine table — effective dates drive date-aware selection."
        right={<Button onClick={() => setOpen(blank)}>+ Add Rule</Button>}
      />
      <ErrorBox error={error} />
      <div className="mb-3 flex gap-2">
        {["", "active", "superseded", "draft"].map((s) => (
          <button key={s} onClick={() => setFilter(s)} className={"rounded-lg px-3 py-1.5 text-xs font-bold " + (filter === s ? "bg-navy-700 text-white" : "border border-slate-200 bg-white text-slate-600")}>
            {s ? s.toUpperCase() : "ALL"}
          </button>
        ))}
      </div>
      <Card className="overflow-hidden">
        {loading ? (
          <Spinner />
        ) : items.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-400">
            No rules found{filter ? ` with status "${filter}"` : ""}. {!filter && "The rule database may not be seeded yet."}
          </div>
        ) : (
          <Table head={["Rule", "Sub-rule", "Title", "Type", "Severity", "Effective", "Status", ""]}>
            {items.map((r) => (
              <tr key={r.id} className="hover:bg-slate-50">
                <td className="px-3 py-2 font-mono text-xs text-navy-700">{r.rule_id}</td>
                <td className="px-3 py-2 font-semibold">{r.rule_number} {r.sub_rule}</td>
                <td className="px-3 py-2 text-xs">{r.title}</td>
                <td className="px-3 py-2"><Badge value={r.type} /></td>
                <td className="px-3 py-2"><Badge value={r.severity} /></td>
                <td className="px-3 py-2 text-xs">{r.effective_from}{r.effective_to ? ` → ${r.effective_to}` : " → ∞"} · v{r.version}</td>
                <td className="px-3 py-2"><Badge value={r.status} /></td>
                <td className="px-3 py-2">
                  <div className="flex gap-1">
                    <Button variant="secondary" className="px-2 py-1 text-[10px]" onClick={() => setOpen({ ...r })}>Edit</Button>
                    {r.status === "active" && <Button variant="danger" className="px-2 py-1 text-[10px]" onClick={() => deactivate(r)}>Supersede</Button>}
                  </div>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {open && (
        <Modal open onClose={() => setOpen(null)} title={open.__new ? "Add Rule" : `Edit ${open.rule_id}`} wide>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Rule Number"><input className={inputCls} value={open.rule_number} onChange={(e) => setOpen({ ...open, rule_number: e.target.value })} /></Field>
            <Field label="Sub-Rule"><input className={inputCls} value={open.sub_rule} onChange={(e) => setOpen({ ...open, sub_rule: e.target.value })} /></Field>
            <Field label="Title"><input className={inputCls} value={open.title} onChange={(e) => setOpen({ ...open, title: e.target.value })} /></Field>
            <Field label="Type">
              <select className={inputCls} value={open.type} onChange={(e) => setOpen({ ...open, type: e.target.value })}>
                {["content", "font", "placement", "spacing", "format"].map((t) => <option key={t}>{t}</option>)}
              </select>
            </Field>
            <div className="sm:col-span-2">
              <Field label="Requirement"><textarea className={inputCls} rows={2} value={open.requirement} onChange={(e) => setOpen({ ...open, requirement: e.target.value })} /></Field>
            </div>
            <Field label="Severity">
              <select className={inputCls} value={open.severity} onChange={(e) => setOpen({ ...open, severity: e.target.value })}>
                {["critical", "major", "minor"].map((t) => <option key={t}>{t}</option>)}
              </select>
            </Field>
            <Field label="Status">
              <select className={inputCls} value={open.status} onChange={(e) => setOpen({ ...open, status: e.target.value })}>
                {["active", "draft", "superseded"].map((t) => <option key={t}>{t}</option>)}
              </select>
            </Field>
            <Field label="Effective From"><input className={inputCls} type="date" value={open.effective_from} onChange={(e) => setOpen({ ...open, effective_from: e.target.value })} /></Field>
            <Field label="Effective To (blank = in force)">
              <input className={inputCls} type="date" value={open.effective_to || ""} onChange={(e) => setOpen({ ...open, effective_to: e.target.value || null })} />
            </Field>
            <Field label="Version"><input className={inputCls} type="number" value={open.version} onChange={(e) => setOpen({ ...open, version: +e.target.value })} /></Field>
            <Field label="Source / Citation"><input className={inputCls} value={open.source} onChange={(e) => setOpen({ ...open, source: e.target.value })} /></Field>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setOpen(null)}>Cancel</Button>
            <Button onClick={save} disabled={busy}>{busy ? "Saving…" : open.__new ? "Create Rule" : "Save Rule"}</Button>
          </div>
        </Modal>
      )}
    </div>
  );
}
