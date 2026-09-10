import { useEffect, useState } from "react";
import { api } from "../client";
import { Badge, Button, Card, ErrorBox, Field, Modal, PageTitle, Spinner, Table, inputCls } from "../components/ui";

export default function AdminInspectors() {
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ username: "", full_name: "", department: "", password: "inspector123", status: "active" });
  const [busy, setBusy] = useState(false);

  const load = () => api.get("/admin/inspectors").then((d) => setItems(d.items)).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const setStatus = async (u: any, status: string) => {
    try {
      await api.patch(`/admin/inspectors/${u.id}`, { status });
      await load();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const create = async () => {
    // NOTE — account provisioning is 100% backend-driven. The browser never
    // stores or fakes the inspector: this POST inserts a real row into the
    // PostgreSQL `users` table (role=inspector, password hashed server-side).
    // There is deliberately NO localStorage fallback here — accounts must
    // survive browser/device changes and be visible to other sessions.
    if (!form.username.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api.post("/admin/inspectors", form);
      setAddOpen(false);
      setForm({ username: "", full_name: "", department: "", password: "inspector123", status: "active" });
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageTitle
        title="Inspectors"
        subtitle="Inspector accounts are provisioned by the administrator — there is no self-registration."
        right={<Button onClick={() => setAddOpen(true)}>+ Add Inspector</Button>}
      />
      <ErrorBox error={error} />
      <Card className="overflow-hidden">
        {!items.length ? (
          <Spinner />
        ) : (
          <Table head={["Inspector ID", "Name", "Department", "Status", "Last Active", "Actions"]}>
            {items.map((u) => (
              <tr key={u.id} className="hover:bg-slate-50">
                <td className="px-3 py-2 font-semibold text-navy-700">{u.username}</td>
                <td className="px-3 py-2">{u.full_name}</td>
                <td className="px-3 py-2 text-xs">{u.department}</td>
                <td className="px-3 py-2"><Badge value={u.status} /></td>
                <td className="px-3 py-2 text-xs">{u.last_active_at ? new Date(u.last_active_at).toLocaleString("en-IN") : "—"}</td>
                <td className="px-3 py-2">
                  <div className="flex gap-1">
                    {u.status !== "active" && <Button variant="success" className="px-2 py-1 text-[10px]" onClick={() => setStatus(u, "active")}>Activate</Button>}
                    {u.status === "active" && (
                      <>
                        <Button variant="secondary" className="px-2 py-1 text-[10px]" onClick={() => setStatus(u, "pending")}>Suspend</Button>
                        <Button variant="danger" className="px-2 py-1 text-[10px]" onClick={() => setStatus(u, "inactive")}>Deactivate</Button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Modal open={addOpen} onClose={() => setAddOpen(false)} title="Add Inspector">
        <div className="space-y-3">
          <Field label="Inspector ID *">
            <input className={inputCls} placeholder="e.g. LM-INS-00200" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
          </Field>
          <Field label="Full Name">
            <input className={inputCls} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          </Field>
          <Field label="Department">
            <input className={inputCls} value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} />
          </Field>
          <Field label="Initial Password">
            <input className={inputCls} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </Field>
          <Field label="Account Status">
            <select className={inputCls} value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
              <option value="active">Active</option>
              <option value="pending">Pending</option>
              <option value="inactive">Inactive</option>
            </select>
          </Field>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button onClick={create} disabled={busy}>{busy ? "Creating…" : "Create Inspector Account"}</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
