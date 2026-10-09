import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { I18nProvider } from "../i18n";
import { TrashSection } from "./Trash";
import { ConfirmProvider, useConfirm } from "./ui";

const items = [
  { id: "t1", kind: "sessions", label: "Example Surgery", deleted_at: "2026-10-09T10:00:00+00:00", purge_on: "2026-11-08",
    summary: { count: 1, practice: "Example Surgery", date: "2026-10-13", last_date: "2026-10-13", unit: "am" } },
  { id: "t2", kind: "invoice", label: "Example Surgery", deleted_at: "2026-10-08T10:00:00+00:00", purge_on: "2026-11-07",
    summary: { practice: "Example Surgery", total: "677.65", lines: 1 } },
  { id: "t3", kind: "payment", label: "LOC-2026-0001", deleted_at: "2026-10-07T10:00:00+00:00", purge_on: "2026-11-06",
    summary: { amount: "100.00", invoice_number: "LOC-2026-0001", refund: false } },
  { id: "document:d1", kind: "document", label: "Booking email", deleted_at: "2026-10-06T10:00:00+00:00", purge_on: "2026-11-05",
    summary: { doc_kind: "booking", filename: null } },
];

describe("Recently deleted", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lists deleted things in plain words and restores one", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") return new Response(JSON.stringify({ kind: "sessions", restored: 1, skipped: 0 }), { status: 200 });
      return new Response(JSON.stringify({ items: url.includes("/trash") ? items : [] }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<I18nProvider><TrashSection /></I18nProvider>);
    expect(await screen.findByText("Session · Tue 13 Oct (AM) · Example Surgery")).toBeInTheDocument();
    expect(screen.getByText("Draft invoice · Example Surgery · £677.65")).toBeInTheDocument();
    expect(screen.getByText("Payment of £100.00 · LOC-2026-0001")).toBeInTheDocument();
    expect(screen.getByText("Inbox file · Booking email")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Restore" })[3]);
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/v1/trash/document%3Ad1/restore", expect.objectContaining({ method: "POST" })),
    );
  });

  it("asks before deleting; Cancel keeps it", async () => {
    const seen: boolean[] = [];
    function Remover() {
      const confirm = useConfirm();
      const [n, setN] = useState(0);
      return (
        <button onClick={async () => {
          seen.push(await confirm({ title: "Delete the session on Tue 13 Oct (AM) at Example Surgery?", confirm: "Delete" }));
          setN(n + 1);
        }}>remove {n}</button>
      );
    }
    render(<I18nProvider><ConfirmProvider><Remover /></ConfirmProvider></I18nProvider>);
    fireEvent.click(screen.getByText("remove 0"));
    expect(await screen.findByText("Delete the session on Tue 13 Oct (AM) at Example Surgery?")).toBeInTheDocument();
    expect(screen.getByText(/Recently deleted for 30 days/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await screen.findByText("remove 1");
    fireEvent.click(screen.getByText("remove 1"));
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await screen.findByText("remove 2");
    expect(seen).toEqual([false, true]);
  });
});
