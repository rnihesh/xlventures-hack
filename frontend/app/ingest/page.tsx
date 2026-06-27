import { IngestPanel } from "@/components/ingest-panel";
import { PageHeader } from "@/components/ui/page-header";

export const metadata = {
  title: "Ingest | Aperture",
  description:
    "Import live customer interactions into the retrieval corpus so the engine can cite them.",
};

export default function IngestPage() {
  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-8">
      <PageHeader
        eyebrow="Retrieval"
        title="Ingest"
        description="Feed the engine a live customer interaction so it can cite the evidence in future recommendations."
      />
      <IngestPanel />
    </div>
  );
}
