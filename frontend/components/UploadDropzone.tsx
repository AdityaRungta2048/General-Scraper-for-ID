import { useRef, useState, type DragEvent } from "react";

const ACCEPTED = [".xlsx", ".xlsm"];

export function isAcceptedFile(name: string): boolean {
  const lower = name.toLowerCase();
  return ACCEPTED.some((ext) => lower.endsWith(ext));
}

export default function UploadDropzone({ onFile, disabled }: { onFile: (file: File) => void; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handle = (file: File | undefined) => {
    if (!file) return;
    if (!isAcceptedFile(file.name)) {
      setError("Please choose an Excel workbook (.xlsx or .xlsm).");
      return;
    }
    setError(null);
    onFile(file);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    if (!disabled) handle(e.dataTransfer.files?.[0]);
  };

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition ${
          dragging ? "border-brand-500 bg-brand-50" : "border-zinc-300 bg-zinc-50"
        } ${disabled ? "opacity-60" : ""}`}
        data-testid="dropzone"
      >
        <div className="text-base font-semibold text-zinc-800">Drag &amp; drop an Excel file</div>
        <div className="mt-1 text-sm text-zinc-500">
          Headers like <code>id_twitch | country | id_youtube | remarks</code>: an <code>id_&lt;platform&gt;</code>{" "}
          column for the source and one for the destination (<code>id_twitch</code>, <code>id_kick</code>,{" "}
          <code>id_youtube</code>)
        </div>
        <div className="my-4 text-xs uppercase tracking-wide text-zinc-400">or</div>
        <button
          type="button"
          disabled={disabled}
          onClick={() => input.current?.click()}
          className="rounded-lg bg-white px-4 py-2 text-sm font-semibold text-zinc-800 ring-1 ring-inset ring-zinc-300 hover:bg-zinc-100"
        >
          Choose Excel File
        </button>
        <input
          ref={input}
          type="file"
          accept=".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          className="hidden"
          aria-label="Excel file"
          onChange={(e) => handle(e.target.files?.[0])}
        />
      </div>
      {error && <p className="mt-2 text-sm text-rose-700">{error}</p>}
    </div>
  );
}
