import { useEffect } from "react";
import { Route, Routes, useLocation } from "react-router-dom";

import { AdminRoute } from "./components/AdminRoute";
import { AccountSecurityPage } from "./pages/AccountSecurityPage";
import { AdminCreationsPage } from "./pages/AdminCreationsPage";
import { AdminProviderUsagePage } from "./pages/AdminProviderUsagePage";
import { HelpPage, NotFoundPage, RegistrationAdminPage } from "./pages/AdminHelpPages";
import { RuntimeSettingsPage } from "./pages/AdminRuntimeSettingsPage";
import { AuthPage } from "./pages/AuthPages";
import { DevicesPage } from "./pages/DevicesPage";
import { JianyingExportPage } from "./pages/JianyingExportPage";
import { CatalogPage, DetailPage } from "./pages/MarketplacePages";
import { ProfilePage } from "./pages/ProfilePage";
import { RecordsPage } from "./pages/RecordsPage";
import { AccountUsagePage, AdminUserQuotaPage } from "./pages/QuotaPages";
import { StudioPage } from "./pages/StudioPage";
import { VoicesPage } from "./pages/VoicesPage";

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [pathname]);
  return null;
}

export default function App() {
  return (
    <>
      <ScrollToTop />
      <Routes>
        <Route path="/" element={<StudioPage />} />
        <Route path="/workflows" element={<CatalogPage />} />
        <Route path="/workflows/:code" element={<DetailPage />} />
        <Route path="/voices" element={<VoicesPage />} />
        <Route path="/records" element={<RecordsPage />} />
        <Route path="/devices" element={<AdminRoute><DevicesPage /></AdminRoute>} />
        <Route path="/jianying-export" element={<JianyingExportPage />} />
        <Route path="/jianying-export/test" element={<JianyingExportPage />} />
        <Route path="/account" element={<ProfilePage />} />
        <Route path="/account/security" element={<AccountSecurityPage />} />
        <Route path="/account/usage" element={<AccountUsagePage />} />
        <Route path="/login" element={<AuthPage mode="login" />} />
        <Route path="/register" element={<AuthPage mode="register" />} />
        <Route path="/admin/registrations" element={<AdminRoute><RegistrationAdminPage /></AdminRoute>} />
        <Route path="/admin/creations" element={<AdminRoute><AdminCreationsPage /></AdminRoute>} />
        <Route path="/admin/provider-usage" element={<AdminRoute><AdminProviderUsagePage /></AdminRoute>} />
        <Route path="/admin/runtime-settings" element={<AdminRoute><RuntimeSettingsPage /></AdminRoute>} />
        <Route path="/admin/user-quotas" element={<AdminRoute><AdminUserQuotaPage /></AdminRoute>} />
        <Route path="/help" element={<HelpPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </>
  );
}
