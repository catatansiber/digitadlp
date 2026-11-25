import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppRoutes, makeQueryClient } from "../App";
import { QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../auth/AuthProvider";

export function renderApp(path = "/") {
  const qc = makeQueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
