import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "../i18n";
import InvoicesPage from "./Invoices";

const page = {
  items: [
    { id: "1", status: "issued", invoice_number: "LOC-2026-0001", practice_id: "p", practice_name: "Example Medical Practice",
      invoice_date: "2026-10-20", due_date: "2026-11-19", work_start_date: "2026-10-08", work_end_date: "2026-10-15",
      grand_total: "1411.78", archive: { status: "pending", webdav_enabled: true } },
    { id: "2", status: "draft", invoice_number: null, practice_id: "p", practice_name: "Example Medical Practice",
      invoice_date: null, due_date: null, work_start_date: "2026-10-22", work_end_date: "2026-10-22",
      grand_total: "677.65", archive: { status: "not_configured", webdav_enabled: true } },
  ],
  total: 2, page: 1, page_size: 25,
};

describe("InvoicesPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(page), { status: 200 })));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("lists drafts and issued invoices with totals and archive status", async () => {
    render(
      <I18nProvider>
        <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <InvoicesPage />
        </MemoryRouter>
      </I18nProvider>,
    );
    expect((await screen.findAllByText("LOC-2026-0001")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("£1,411.78").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Nextcloud backup pending").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Draft").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /New invoice/ })).toHaveAttribute("href", "/invoices/new");
  });
});
