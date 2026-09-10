import { useEffect, useState } from "react";
import { api, fmtDateTime } from "../client";
import { Card, ErrorBox, PageTitle, Spinner, Table } from "../components/ui";

export default function AdminAudit() {
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    api.get("/admin/audit").then((d) => setItems(d.items)).catch((e) => setError(e.message));
  }, []);
  return (
    <div>
      <PageTitle title="Audit Logs" subtitle="Every important system and inspection action is recorded — engine results are never overwritten by inspector decisions." />
      <ErrorBox error={error} />
      <Card className="overflow-hidden">
        {!items.length && !error ? (
          <Spinner />
        ) : (
          <Table head={["When", "Actor", "Role", "Action", "Entity", "Details"]}>
            {items.map((a) => (
              <tr key={a.id} className="hover:bg-slate-50">
                <td className="px-3 py-2 whitespace-nowrap text-xs">{fmtDateTime(a.created_at)}</td>
                <td className="px-3 py-2 font-semibold text-navy-700">{a.actor}</td>
                <td className="px-3 py-2 text-xs uppercase">{a.actor_role}</td>
                <td className="px-3 py-2 text-xs font-semibold">{a.action.replace(/_/g, " ")}</td>
                <td className="px-3 py-2 text-xs">{a.entity_type} {a.entity_id}</td>
                <td className="px-3 py-2 text-xs text-slate-500">{a.details ? JSON.stringify(a.details).slice(0, 80) : "—"}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
