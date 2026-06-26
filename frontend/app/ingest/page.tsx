import { Upload } from "lucide-react";

import { IngestPanel } from "@/components/ingest-panel";

export const metadata = {
  title: "Ingest | Aperture",
  description:
    "Import live customer interactions into the retrieval corpus so the engine can cite them.",
};

export default function IngestPage() {
  return (
    <div className="flex flex-1 flex-col">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
            <Upload className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-sm font-medium text-muted-foreground">Ingest</h1>
            <p className="text-lg font-semibold tracking-tight">
              Feed the engine a live interaction
            </p>
          </div>
        </div>
      </header>

      <div className="mx-auto w-full max-w-6xl px-6 py-8">
        <IngestPanel />
      </div>
    </div>
  );
}
