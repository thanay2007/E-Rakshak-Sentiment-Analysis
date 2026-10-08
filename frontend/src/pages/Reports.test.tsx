import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Reports from "./Reports";
import { api } from "../services/api";

const mocks = vi.hoisted(() => ({
  report: { id: "report-1", kind: "incident", title: "Incident summary", created_at: "2026-10-08T12:00:00Z", period_hours: 24, payload: {}, has_pdf: true, has_xlsx: true },
  refresh: vi.fn(),
}));
vi.mock("../components/PostDetailProvider", () => ({ usePostDetail: () => ({ openPostId: vi.fn() }) }));
vi.mock("../hooks/usePolling", () => ({ usePolling: () => ({ data: [mocks.report], loading: false, refresh: mocks.refresh }) }));
vi.mock("../hooks/useGsapReveal", () => ({ useGsapReveal: () => ({ current: null }) }));
vi.mock("../services/api", () => ({ api: {
  generateReport: vi.fn(), report: vi.fn(), downloadReport: vi.fn(), downloadReportXlsx: vi.fn(),
} }));
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.generateReport).mockResolvedValue(mocks.report);
  vi.mocked(api.report).mockResolvedValue(mocks.report);
  vi.mocked(api.downloadReport).mockResolvedValue(undefined);
  vi.mocked(api.downloadReportXlsx).mockResolvedValue(undefined);
});
afterEach(cleanup);

it("shows a generated confirmation without opening a preview or downloading", async () => {
  render(<Reports />);
  fireEvent.click(screen.getByRole("button", { name: "Generate Incident Report" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Report generated.");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(api.downloadReport).not.toHaveBeenCalled();
  expect(api.downloadReportXlsx).not.toHaveBeenCalled();
  expect(mocks.refresh).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "Dismiss message" }));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("shows a short failure message and lets the officer try again", async () => {
  vi.mocked(api.generateReport).mockRejectedValueOnce(new Error("Server failure"));
  render(<Reports />);
  fireEvent.click(screen.getByRole("button", { name: "Generate Incident Report" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not create the report. Please try again.");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.queryByText("Reload console")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Generate Incident Report" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Report generated.");
});

it("waits for generation to finish before showing success and prevents repeated clicks", async () => {
  let resolve!: (report: typeof mocks.report) => void;
  vi.mocked(api.generateReport).mockReturnValueOnce(new Promise(done => { resolve = done; }));
  render(<Reports />);
  fireEvent.click(screen.getByRole("button", { name: "Generate Incident Report" }));
  const button = screen.getByRole("button", { name: "Creating Report…" });
  expect(button).toBeDisabled();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  fireEvent.click(button);
  expect(api.generateReport).toHaveBeenCalledOnce();
  resolve(mocks.report);
  expect(await screen.findByRole("status")).toHaveTextContent("Report generated.");
});

it("still opens existing reports outside the transformed page container", async () => {
  render(<div data-testid="animated-page" style={{ transform: "translateY(16px)", filter: "blur(0px)" }}><Reports /></div>);
  fireEvent.click(screen.getByText("Incident summary"));
  const dialog = await screen.findByRole("dialog", { name: "Report preview" });
  expect(document.body).toContainElement(dialog);
  expect(screen.getByTestId("animated-page")).not.toContainElement(dialog);
  expect(dialog).toHaveAttribute("aria-modal", "true");
  expect(screen.getByRole("button", { name: "Download PDF" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Download Excel" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
});

it("handles failures when opening an existing report without breaking the page", async () => {
  vi.mocked(api.report).mockRejectedValueOnce(new Error("Unavailable"));
  render(<Reports />);
  fireEvent.click(screen.getByText("Incident summary"));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Could not open the report. Please try again."));
  expect(screen.getByRole("button", { name: "Generate Incident Report" })).toBeEnabled();
});


it("shows medium-concern posts with review reasons, next steps, and readable metric names", async () => {
  vi.mocked(api.report).mockResolvedValueOnce({ ...mocks.report, payload: {
    summary_points: ["Two posts need follow-up."], totals: { avg_concern_score: 44 },
    concern_thresholds: { medium: 35, high: 50, critical: 60 },
    top_concern: [], follow_up_posts: [{ id: "medium-post", platform: "X", author_handle: "watch_account",
      language: "English", location: "Surat", text: "Please check this developing situation.",
      sentiment_label: "negative", concern_score: 44, review_reasons: ["Shared 8 times; monitor for wider spread."],
      suggested_action: "Review the post and check the context." }],
  } });
  render(<Reports />);
  fireEvent.click(screen.getByText("Incident summary"));
  await screen.findByRole("dialog", { name: "Report preview" });
  expect(screen.getByRole("heading", { name: "Medium concerns to monitor" })).toBeInTheDocument();
  expect(screen.getByText(/Scores 35–49/)).toBeInTheDocument();
  expect(screen.getByText("Average concern score")).toBeInTheDocument();
  expect(screen.getByText("Shared 8 times; monitor for wider spread.")).toBeInTheDocument();
  expect(screen.getByText("Review the post and check the context.")).toBeInTheDocument();
});

it.each(["PDF", "Excel"])("downloads %s only on request", async format => {
  render(<Reports />);
  fireEvent.click(screen.getByText("Incident summary"));
  const button = await screen.findByRole("button", { name: `Download ${format}` });
  fireEvent.click(button);
  expect(await screen.findByRole("status")).toHaveTextContent(`${format === "PDF" ? "PDF" : "Excel file"} download started.`);
  expect(format === "PDF" ? api.downloadReport : api.downloadReportXlsx).toHaveBeenCalledWith("report-1");
});

it("shows a small message when a PDF download fails and allows retry", async () => {
  vi.mocked(api.downloadReport).mockRejectedValueOnce(new Error("Server failure"));
  render(<Reports />);
  fireEvent.click(screen.getByText("Incident summary"));
  fireEvent.click(await screen.findByRole("button", { name: "Download PDF" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not download the file. Please try again.");
  expect(screen.getByRole("button", { name: "Download PDF" })).toBeEnabled();
});

it("shows seven-day periods in saved titles, summaries, and report metadata", async () => {
  vi.mocked(api.report).mockResolvedValueOnce({ ...mocks.report, period_hours: 168,
    title: "Situation Report — past 168h", payload: { summary_points: ["20 posts checked in the past 168 hours."] },
  });
  render(<Reports />);
  fireEvent.click(screen.getByText("Incident summary"));
  await screen.findByRole("dialog", { name: "Report preview" });
  expect(screen.getByRole("heading", { name: "Situation Report — past 7 days" })).toBeInTheDocument();
  expect(screen.getByText("20 posts checked in the past 7 days.")).toBeInTheDocument();
  expect(screen.getByText(/IST · Past 7 days/)).toBeInTheDocument();
  expect(screen.queryByText(/168h/)).not.toBeInTheDocument();
});
