import { useEffect, useRef } from "react";

export interface PdfDownloadProps {
  title: string;
  data?: Uint8Array | undefined;
  href?: string | undefined;
  label?: string;
}

/** Download loaded PDF bytes or a trusted, registered PDF asset. */
export function PdfDownload({ title, data, href, label = "Download PDF" }: PdfDownloadProps) {
  const downloadUrl = useRef<string | null>(null);
  useEffect(() => () => {
    if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current);
    downloadUrl.current = null;
  }, [data]);
  const safeTitle = title.replace(/[\\/:*?"<>|\u0000-\u001f]/g, "-").trim();
  const filename = `${safeTitle.replace(/\.pdf$/i, "") || "document"}.pdf`;
  const icon = (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M12 3v12m-4-4 4 4 4-4M5 16v5h14v-5" />
    </svg>
  );

  function download() {
    if (!data) return;
    if (!downloadUrl.current) {
      downloadUrl.current = URL.createObjectURL(
        new Blob([data.slice()], { type: "application/pdf" }),
      );
    }
    const link = window.document.createElement("a");
    link.href = downloadUrl.current;
    link.download = filename;
    link.click();
  }

  if (!data && href) {
    return (
      <a aria-label={label} className="ca-document-download" download={filename}
        href={href} title={label}>
        {icon}
      </a>
    );
  }
  if (!data) return null;
  return (
    <button aria-label={label} title={label} className="ca-document-download"
      onClick={download} type="button">
      {icon}
    </button>
  );
}
