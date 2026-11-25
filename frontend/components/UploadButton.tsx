"use client";

import { useEffect, useState } from "react";
import { Upload, X } from "lucide-react";
import UploadDropzone from "@/components/UploadDropzone";

/** Compact "Upload" button; the drop zone lives in a dialog so it doesn't take dashboard space. */
export default function UploadButton() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 text-[13px] font-medium px-3 py-1.5 rounded-md border border-hairline bg-white hover:bg-panelRaised"
      >
        <Upload className="w-3.5 h-3.5" /> Upload
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4"
          onClick={() => setOpen(false)}
          role="dialog"
          aria-modal="true"
          aria-label="Upload recordings"
        >
          <div
            className="w-full max-w-xl rounded-lg bg-white border border-hairline shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-3 border-b border-hairline">
              <h2 className="font-display text-[14px] font-semibold">Upload recordings</h2>
              <button onClick={() => setOpen(false)} aria-label="Close" className="text-faint hover:text-ink">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-5">
              <UploadDropzone />
              <p className="text-[12px] text-faint mt-3">
                Uploaded recordings are analysed automatically. You can close this window while they process.
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
