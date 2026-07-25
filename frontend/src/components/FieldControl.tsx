import { LoaderCircle, UploadCloud, X } from "lucide-react";
import { useState } from "react";

import { uploadAsset } from "../api";
import type { InputField } from "../types";

export type UploadedFile = { id: string; name: string; url: string };

export function FieldControl({
  field,
  value,
  onChange,
  onBusy,
}: {
  field: InputField;
  value: unknown;
  onChange: (value: unknown) => void;
  onBusy: (busy: boolean) => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const files = (Array.isArray(value) ? value : value ? [value] : []) as UploadedFile[];
  const isAsset = ["image", "video", "audio", "file"].includes(field.type);

  async function handleFiles(selected: FileList | null) {
    if (!selected?.length) return;
    setUploading(true);
    setUploadError("");
    onBusy(true);
    try {
      const limit = field.multiple ? field.max_files || selected.length : 1;
      const picked = Array.from(selected).slice(0, limit);
      const uploaded = await Promise.all(picked.map(async (file) => {
        const { asset } = await uploadAsset(file);
        return { id: asset.id, name: asset.name, url: asset.url };
      }));
      onChange(field.multiple ? [...files, ...uploaded].slice(0, limit) : uploaded[0]);
    } catch (error) {
      setUploadError((error as Error).message);
    } finally {
      setUploading(false);
      onBusy(false);
    }
  }

  if (isAsset) {
    const accept = field.accept?.join(",") || (field.type === "file" ? ".docx,.txt" : `${field.type}/*`);
    return (
      <div className="asset-control">
        <label className="upload-drop">
          {uploading ? <LoaderCircle className="spin" /> : <UploadCloud />}
          <strong>{uploading ? "正在上传" : field.multiple ? "点击上传多份素材" : "点击上传素材"}</strong>
          <small>{field.multiple ? `最多 ${field.max_files || 9} 个文件` : accept}</small>
          <input type="file" accept={accept} multiple={field.multiple} onChange={(event) => void handleFiles(event.target.files)} />
        </label>
        {files.length > 0 && (
          <div className="uploaded-list">
            {files.map((file) => (
              <span key={file.id}>
                {file.name}
                <button
                  type="button"
                  aria-label={`移除 ${file.name}`}
                  onClick={() => {
                    const next = files.filter((item) => item.id !== file.id);
                    onChange(field.multiple ? next : "");
                  }}
                >
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
        )}
        {uploadError && <div className="notice error">{uploadError}</div>}
      </div>
    );
  }

  if (field.type === "textarea") {
    return <textarea value={String(value ?? "")} placeholder={field.placeholder} onChange={(event) => onChange(event.target.value)} />;
  }
  if (field.type === "notice") {
    return <div className="field-notice">{String(value || field.default || "")}</div>;
  }
  if (field.type === "select") {
    return (
      <select value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}>
        {field.options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    );
  }
  return (
    <input
      type={field.type === "number" ? "number" : "text"}
      min={field.min}
      max={field.max}
      value={String(value ?? "")}
      placeholder={field.placeholder}
      onChange={(event) => onChange(field.type === "number" ? Number(event.target.value) : event.target.value)}
    />
  );
}
