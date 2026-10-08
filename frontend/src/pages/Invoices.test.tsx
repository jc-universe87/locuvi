import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "../i18n";
import InvoicesPage from "./Invoices";

const page = {
  items: [
    { id: "1", status: "issued", invoice_number: "LOC-2026-0001", practice_id: "p", practice_name: "Example Medical Practice",
      invoice_date: "2026-10-20", due_date: "2026-11-19", work_start_date: "2026-10-08", work_end_date: "2026-10-15",
      grand_total: "1411.78", archive: { status: "pending", webdav_enabled: true },
      payment: { state: "overdue", paid: "0.00", outstanding: "1411.78", days_overdue: 3 }, last_emailed_at: null },
    { id: "2", status: "draft", invoice_number: null, practice_id: "p", practice_name: "Example Medical Practice",
      invoice_date: null, due_date: null, work_start_date: "2026-10-22", work_end_date: "2026-10-22",
      grand_total: "677.65", archive: { status: "not_configured", webdav_enabled: true },
      payment: { state: "n/a", paid: null, outstanding: null, days_overdue: 0 }, last_emailed_at: null },
  ],
  total: 2, page: 1, page_size: 25,
};

describe("InvoicesPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(page), { status: 200 })));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("lists drafts and issued invoices with totals, payment and archive status", async () => {
    render(
      <I18nProvider>
        <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <InvoicesPage />
        </MemoryRouter>
      </I18nProvider>,
    );
    expect(await screen.findByText(/LOC-2026-0001/)).toBeInTheDocument();
    expect(screen.getByText("£1,411.78")).toBeInTheDocument();
    expect(screen.getByText("Overdue 3d")).toBeInTheDocument();
    expect(screen.getByText("Nextcloud backup pending")).toBeInTheDocument();
    expect(screen.getAllByText("Draft").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /New invoice/ })).toHaveAttribute("href", "/invoices/new");
  });
});
