import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "../auth";

export function AdminRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return null;
  if (!user) {
    const redirect = `${location.pathname}${location.search}`;
    return <Navigate to={`/login?redirect=${encodeURIComponent(redirect)}`} replace />;
  }
  if (user.role !== "admin") return <Navigate to="/" replace />;
  return <>{children}</>;
}
