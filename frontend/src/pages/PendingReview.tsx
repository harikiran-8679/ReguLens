import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, fmtDate } from "../client";
import { Badge, Button, Card, Empty, ErrorBox, PageTitle, Spinner, Table } from "../components/ui";

export default function PendingReview() {
  const navigate = useNavigate();
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    api.get("/inspections?status=pending_review").then((d) => setItems(d.items)).catch((e) => setError(e.message));
  }, []);
  return (
    <div>
      <PageTitle title="Pending Review" subtitle="Automated analysis is complete; these inspections require your assessment before finalisation." />
      <ErrorBox error={error} />
      <Card className="overflow-hidden">
        {!items.length && !error ? (
          <Empty icon="🎉" text="Nothing pending — every analysed inspection has been reviewed." />
        ) : (
          <Table head={["Inspection", "Product", "Date", "Automated Result", "Failed", "Review", "Action"]}>
            {items.map((r) => (
              <tr key={r.id} className="hover:bg-slate-50">
                <td className="px-3 py-2 font-semibold text-navy-700">{r.inspection_id}</td>
                <td className="px-3 py-2">{r.product_name}</td>
                <td className="px-3 py-2">{fmtDate(r.inspection_date)}</td>
                <td className="px-3 py-2"><Badge value={r.automated_result} /></td>
                <td className="px-3 py-2 font-bold text-red-700">{r.violations_count}</td>
                <td className="px-3 py-2 font-bold text-amber-700">{r.review_count}</td>
                <td className="px-3 py-2">
                  <Button onClick={() => navigate(`/inspector/inspections/${r.id}/review`)}>REVIEW</Button>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
