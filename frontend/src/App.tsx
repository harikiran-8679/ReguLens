import { Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "./components/layout";
import Landing from "./pages/Landing";
import LoginPage from "./pages/Login";
import InspectorDashboard from "./pages/InspectorDashboard";
import NewInspection from "./pages/NewInspection";
import CapturePage from "./pages/Capture";
import OcrPage from "./pages/OcrExtraction";
import RulesPage from "./pages/RuleAnalysis";
import ResultPage from "./pages/ComplianceResult";
import FindingsPage from "./pages/ViolationDetails";
import FontPage from "./pages/FontReadability";
import PlacementPage from "./pages/PlacementFormat";
import EvidencePage from "./pages/EvidencePage";
import ReviewPage from "./pages/InspectorReview";
import ReportPreview from "./pages/ReportPreview";
import ReportExport from "./pages/ReportExport";
import MyInspections from "./pages/MyInspections";
import PendingReview from "./pages/PendingReview";
import ReportsList from "./pages/ReportsList";
import RulesReference from "./pages/RulesReference";
import AdminDashboard from "./pages/AdminDashboard";
import AdminInspectors from "./pages/AdminInspectors";
import AdminRules from "./pages/AdminRules";
import AdminAudit from "./pages/AdminAudit";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login/inspector" element={<LoginPage mode="inspector" />} />
      <Route path="/login/admin" element={<LoginPage mode="admin" />} />

      {/* Inspector workspace */}
      <Route
        path="/inspector"
        element={
          <RequireRole role="inspector">
            <Shell role="inspector" />
          </RequireRole>
        }
      >
        <Route index element={<Navigate to="/inspector/dashboard" replace />} />
        <Route path="dashboard" element={<InspectorDashboard />} />
        <Route path="new" element={<NewInspection />} />
        <Route path="inspections/:id/capture" element={<CapturePage />} />
        <Route path="inspections/:id/ocr" element={<OcrPage />} />
        <Route path="inspections/:id/rules" element={<RulesPage />} />
        <Route path="inspections/:id/result" element={<ResultPage />} />
        <Route path="inspections/:id/findings" element={<FindingsPage />} />
        <Route path="inspections/:id/font" element={<FontPage />} />
        <Route path="inspections/:id/placement" element={<PlacementPage />} />
        <Route path="inspections/:id/evidence" element={<EvidencePage />} />
        <Route path="inspections/:id/review" element={<ReviewPage />} />
        <Route path="inspections/:id/report" element={<ReportPreview />} />
        <Route path="inspections/:id/export" element={<ReportExport />} />
        <Route path="my" element={<MyInspections />} />
        <Route path="pending" element={<PendingReview />} />
        <Route path="reports" element={<ReportsList />} />
        <Route path="rules" element={<RulesReference />} />
      </Route>

      {/* Admin workspace */}
      <Route
        path="/admin"
        element={
          <RequireRole role="admin">
            <Shell role="admin" />
          </RequireRole>
        }
      >
        <Route index element={<Navigate to="/admin/dashboard" replace />} />
        <Route path="dashboard" element={<AdminDashboard />} />
        <Route path="inspectors" element={<AdminInspectors />} />
        <Route path="rules" element={<AdminRules />} />
        <Route path="audit" element={<AdminAudit />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function RequireRole({ role, children }: { role: "inspector" | "admin"; children: React.ReactNode }) {
  const { user } = useAuthValue();
  if (!user) return <Navigate to={`/login/${role}`} replace />;
  if (user.role !== role)
    return <Navigate to={user.role === "admin" ? "/admin/dashboard" : "/inspector/dashboard"} replace />;
  return <>{children}</>;
}

import { useAuth } from "./auth";
function useAuthValue() {
  return useAuth();
}
