import React, { useRef, useState } from "react";
import { downloadExcel, uploadExcel } from "../../api/excel";

interface Props {
  cik: string;
  sessionId: string | null;
  onUploadComplete: (sessionId: string) => void;
}

export function ExcelPanel({ cik, sessionId, onUploadComplete }: Props) {
  const [downloading, setDownloading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleDownload = async () => {
    if (!sessionId) return;
    setDownloading(true);
    setError(null);
    try {
      await downloadExcel(cik, sessionId);
    } catch (e) {
      setError("Download failed. Please try again.");
    } finally {
      setDownloading(false);
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    setUploadResult(null);
    try {
      const result = await uploadExcel(cik, file);
      setUploadResult(`${result.overrides_applied} override(s) saved.`);
      onUploadComplete(result.session_id);
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "Upload failed. Make sure you're uploading a file downloaded from this application.";
      setError(msg);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div className="flex items-center gap-3 flex-wrap">
      <button
        onClick={handleDownload}
        disabled={!sessionId || downloading}
        className="flex items-center gap-2 px-4 py-2 bg-green-700 hover:bg-green-800 disabled:bg-gray-300
                   text-white text-sm font-medium rounded-lg transition-colors"
      >
        {downloading ? (
          <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
        ) : (
          <span>↓</span>
        )}
        Download Excel
      </button>

      <label
        className={`flex items-center gap-2 px-4 py-2 border-2 border-dashed
                    ${uploading ? "border-gray-300 text-gray-400" : "border-blue-400 text-blue-700 hover:bg-blue-50 cursor-pointer"}
                    text-sm font-medium rounded-lg transition-colors`}
      >
        {uploading ? (
          <>
            <span className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            Uploading...
          </>
        ) : (
          <>
            <span>↑</span>
            Upload Excel
          </>
        )}
        <input
          ref={fileRef}
          type="file"
          accept=".xlsx"
          onChange={handleFileChange}
          disabled={uploading}
          className="hidden"
        />
      </label>

      {uploadResult && (
        <span className="text-sm text-green-700 font-medium">{uploadResult}</span>
      )}
      {error && <span className="text-sm text-red-600">{error}</span>}
    </div>
  );
}
