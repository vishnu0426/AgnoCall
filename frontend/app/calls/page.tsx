import { api, CallListResponse } from "@/lib/api";
import CallsList from "@/components/CallsList";
import SavedViews from "@/components/SavedViews";
import { Download } from "lucide-react";
import CallsFilterBar from "@/components/CallsFilterBar";
import PageContainer from "@/components/PageContainer";
import Pagination from "@/components/Pagination";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 25;

export default async function CallsPage({
  searchParams,
}: {
  searchParams: Promise<{
    page?: string; status?: string; risk_level?: string;
    agent_id?: string; days?: string; has_violations?: string; search?: string;
    reviewed?: string; sort?: string; order?: string; category?: string; conversation?: string;
  }>;
}) {
  const sp = await searchParams;
  const { page: pageParam, status, risk_level: riskLevel, agent_id: agentId, search } = sp;
  const days = Number(sp.days) > 0 ? Number(sp.days) : undefined;
  const hasViolations = sp.has_violations === "true" ? true : sp.has_violations === "false" ? false : undefined;
  const reviewed = sp.reviewed === "true" ? true : sp.reviewed === "false" ? false : undefined;
  const conversation = sp.conversation === "true" ? true : sp.conversation === "false" ? false : undefined;
  const order: "asc" | "desc" | undefined = sp.order === "asc" ? "asc" : sp.order === "desc" ? "desc" : undefined;
  const page = Math.max(1, Number(pageParam) || 1);
  const query = {
    status, riskLevel, agentId, days, hasViolations, search, reviewed, sort: sp.sort, order,
    category: sp.category || undefined, conversation,
  };

  let loadError = false;
  let data: CallListResponse = { items: [], total: 0, page, page_size: PAGE_SIZE };
  try {
    data = await api.listCalls({ page, pageSize: PAGE_SIZE, ...query });
  } catch {
    loadError = true;   // shown below: an empty table must not pass for "no calls"
  }

  return (
    <PageContainer>
      <header className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-[20px] font-semibold tracking-tight">Calls</h1>
          <p className="text-muted text-[13px] mt-1">
            {data.total} recording{data.total === 1 ? "" : "s"}{sp.sort ? "" : ", most recent first"}. Click a column heading to sort.
          </p>
        </div>
        <a
          href={api.callsExportUrl(query)}
          download
          className="inline-flex items-center gap-1.5 text-[13px] font-medium px-3 py-1.5 rounded-md border border-hairline bg-white hover:border-accent/60"
          title="Download the calls matching the current filters (up to 5,000) as a spreadsheet"
        >
          <Download className="w-3.5 h-3.5" /> Export CSV
        </a>
      </header>
      {loadError && (
        <div className="mb-4 text-[13px] text-bad border border-bad/30 bg-bad/5 rounded-md px-3 py-2">
          The call list could not be loaded. Check that the API is running, then refresh.
        </div>
      )}

      <SavedViews />
      <CallsFilterBar />
      <CallsList calls={data.items} />
      <Pagination
        page={data.page}
        pageSize={data.page_size}
        total={data.total}
        basePath="/calls"
        extraParams={{
          status, risk_level: riskLevel, agent_id: agentId, days: sp.days,
          has_violations: sp.has_violations, search, reviewed: sp.reviewed, sort: sp.sort, order: sp.order,
        }}
      />
    </PageContainer>
  );
}
