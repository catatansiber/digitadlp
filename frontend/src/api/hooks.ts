import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import type { DocSummary } from "./types";

export type DocFilter = { status?: string; mine?: boolean };

const ACTIVE = new Set(["diproses", "membuat_versi"]);

export function useDocuments(filter: DocFilter = {}) {
  return useQuery({
    queryKey: ["documents", filter.status ?? "", !!filter.mine],
    queryFn: () => {
      const p = new URLSearchParams();
      if (filter.status) p.set("status", filter.status);
      if (filter.mine) p.set("mine", "true");
      const qs = p.toString();
      return api<DocSummary[]>("/documents" + (qs ? "?" + qs : ""));
    },
    refetchInterval: (q) => (q.state.data?.some((d) => ACTIVE.has(d.status)) ? 5000 : false),
  });
}
