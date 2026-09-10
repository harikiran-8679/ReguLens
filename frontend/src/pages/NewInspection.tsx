import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../client";
import { Button, Card, ErrorBox, Field, PageTitle, Spinner, inputCls } from "../components/ui";

const EMPTY = {
  product_name: "",
  brand: "",
  product_description: "",
  product_category: "",
  package_type: "",
  retailer_store: "",
  location: "",
  premises_type: "",
  country_of_origin_claimed: "",
};

export default function NewInspection() {
  const navigate = useNavigate();
  const [catalog, setCatalog] = useState<any>(null);
  const [form, setForm] = useState<any>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/meta/catalog").then(setCatalog).catch(() => {});
  }, []);

  const set = (k: string) => (e: any) => setForm((f: any) => ({ ...f, [k]: e.target.value }));

  const create = async () => {
    if (!form.product_category) {
      setError("Select a product category to continue.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const insp = await api.post("/inspections", form);
      await api.post(`/inspections/${insp.id}/navigate`, { step: 2 });
      navigate(`/inspector/inspections/${insp.id}/capture`);
    } catch (e: any) {
      setError(e.message);
      setBusy(false);
    }
  };

  if (!catalog) return <Spinner label="Loading product catalogue…" />;

  return (
    <div>
      <PageTitle
        title="New Inspection"
        subtitle="Step 1 of 7 · Inspection details — record where and what you are inspecting."
        right={
          <Button variant="secondary" onClick={() => navigate("/inspector/dashboard")}>← Dashboard</Button>
        }
      />
      <ErrorBox error={error} />
      <Card className="p-6">
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Product / Brand Name">
            <input className={inputCls} value={form.product_name} onChange={set("product_name")} placeholder="e.g. ABC Premium Rice" />
          </Field>
          <Field label="Brand (if different)">
            <input className={inputCls} value={form.brand} onChange={set("brand")} placeholder="e.g. ABC Foods" />
          </Field>
          <Field label="Product Description / Variant">
            <input className={inputCls} value={form.product_description} onChange={set("product_description")} placeholder="e.g. Extra long grain, 5 kg bag" />
          </Field>
          <Field label="Product Category *" hint="drives the applicable rule set">
            <select className={inputCls} value={form.product_category} onChange={set("product_category")}>
              <option value="">Select category…</option>
              {catalog.categories.map((c: any) => (
                <option key={c.code} value={c.code}>{c.label}{c.imported_only ? " (imported)" : ""}</option>
              ))}
            </select>
          </Field>
          <Field label="Package Type">
            <select className={inputCls} value={form.package_type} onChange={set("package_type")}>
              <option value="">Select…</option>
              {catalog.package_types.map((t: string) => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>
          <Field label="Retailer / Store">
            <input className={inputCls} value={form.retailer_store} onChange={set("retailer_store")} placeholder="e.g. FreshMart Supermarket" />
          </Field>
          <Field label="Inspection Location">
            <input className={inputCls} value={form.location} onChange={set("location")} placeholder="e.g. MG Road, Hyderabad" />
          </Field>
          <Field label="Premises Type">
            <select className={inputCls} value={form.premises_type} onChange={set("premises_type")}>
              <option value="">Select…</option>
              {(catalog.premises_types || []).map((t: string) => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>
          <Field label="Claimed Country of Origin" hint="choose Imported for origin rules">
            <select className={inputCls} value={form.country_of_origin_claimed} onChange={set("country_of_origin_claimed")}>
              <option value="">Not recorded</option>
              <option value="India">India</option>
              <option value="Imported">Imported (non-India)</option>
            </select>
          </Field>
        </div>
        <div className="mt-6 flex items-center justify-between border-t border-slate-200 pt-4">
          <Button variant="secondary" onClick={() => navigate("/inspector/dashboard")}>← Back</Button>
          <Button onClick={create} disabled={busy}>
            {busy ? "Creating…" : "Save Details & Continue →"}
          </Button>
        </div>
      </Card>
    </div>
  );
}
