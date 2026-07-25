import { useEffect } from "react";
import { Route, Routes, useLocation } from "react-router-dom";

import { AccountSecurityPage } from "./pages/AccountSecurityPage";
import { HelpPage, NotFoundPage, RegistrationAdminPage } from "./pages/AdminHelpPages";
import { AuthPage } from "./pages/AuthPages";
import { DevicesPage } from "./pages/DevicesPage";
import { JianyingExportPage } from "./pages/JianyingExportPage";
import { CatalogPage, DetailPage } from "./pages/MarketplacePages";
import { RecordsPage } from "./pages/RecordsPage";
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
        <Route path="/devices" element={<DevicesPage />} />
        <Route path="/jianying-export" element={<JianyingExportPage />} />
        <Route path="/account/security" element={<AccountSecurityPage />} />
        <Route path="/login" element={<AuthPage mode="login" />} />
        <Route path="/register" element={<AuthPage mode="register" />} />
        <Route path="/admin/registrations" element={<RegistrationAdminPage />} />
        <Route path="/help" element={<HelpPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </>
  );
}
