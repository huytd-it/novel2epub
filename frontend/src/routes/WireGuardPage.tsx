import { useEffect, useRef, useState } from "react";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import {
  useActivateProfile,
  useDeleteProfile,
  useDiscoverProfiles,
  useImportWireGuardProfile,
  useProvisionProfile,
  useRotateProfile,
  useSaveWireGuardSettings,
  useSetProfileEnabled,
  useSetProfilePosition,
  useWireGuardOverview,
  type WireGuardProfile,
} from "@/lib/wireguard";
import { Panel, PanelHeader, EmptyState } from "@/components/ui/Panel";
import { Button, Spinner } from "@/components/ui/Button";
import { Checkbox, Field, Input, Textarea } from "@/components/ui/Field";
import { ConfirmDialog } from "@/components/ui/Modal";
import { Badge } from "@/components/ui/Badge";
import { useToast } from "@/components/ui/Toast";
import { IconTrash } from "@/components/icons";

const STATUS_TONE: Record<string, "celadon" | "vermilion" | "neutral"> = {
  active: "celadon",
  error: "vermilion",
};

function ProfileRow({ profile, isFirst, isLast }: { profile: WireGuardProfile; isFirst: boolean; isLast: boolean }) {
  const setEnabled = useSetProfileEnabled();
  const setPosition = useSetProfilePosition();
  const activate = useActivateProfile();
  const del = useDeleteProfile();
  const toast = useToast();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmActivate, setConfirmActivate] = useState(false);

  const onError = (err: unknown) => toast(err instanceof Error ? err.message : String(err), "error");

  return (
    <tr className={clsx("border-b border-base-300 last:border-b-0", profile.status === "active" && "bg-success/5")}>
      <td className="px-2 py-1.5">
        <code className="text-xs">{profile.filename}</code>
      </td>
      <td className="px-2 py-1.5 text-[13px] opacity-70">{profile.source}</td>
      <td className="px-2 py-1.5">
        <Badge tone={STATUS_TONE[profile.status] ?? "neutral"}>
          {profile.status === "active" ? "active" : profile.status === "error" ? "lỗi" : "inactive"}
        </Badge>
      </td>
      <td className="px-2 py-1.5 text-[13px] opacity-70">{profile.enabled ? "Bật" : "Tắt"}</td>
      <td className="px-2 py-1.5">
        <div className="flex items-center gap-1">
          <Button size="sm" disabled={isFirst} onClick={() => setPosition.mutate({ id: profile.id, position: profile.position - 1 }, { onError })}>
            Lên
          </Button>
          <Button size="sm" disabled={isLast} onClick={() => setPosition.mutate({ id: profile.id, position: profile.position + 1 }, { onError })}>
            Xuống
          </Button>
        </div>
      </td>
      <td className="px-2 py-1.5 text-right">
        <div className="flex flex-wrap justify-end gap-1">
          <Button
            size="sm"
            loading={setEnabled.isPending}
            onClick={() => setEnabled.mutate({ id: profile.id, enabled: !profile.enabled }, { onError })}
          >
            {profile.enabled ? "Tắt" : "Bật"}
          </Button>
          <Button size="sm" onClick={() => setConfirmActivate(true)}>
            Kích hoạt
          </Button>
          <Button size="sm" variant="danger" icon={<IconTrash size={12} />} onClick={() => setConfirmDelete(true)} />
        </div>
      </td>

      <ConfirmDialog
        open={confirmActivate}
        onCancel={() => setConfirmActivate(false)}
        onConfirm={() =>
          activate.mutate(profile.id, {
            onSuccess: () => setConfirmActivate(false),
            onError: (err) => {
              setConfirmActivate(false);
              onError(err);
            },
          })
        }
        title="Kích hoạt profile"
        body={`Kích hoạt "${profile.filename}"? Điều này cài tunnel service WireGuard thật.`}
        confirmLabel="Kích hoạt"
        pending={activate.isPending}
      />
      <ConfirmDialog
        open={confirmDelete}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() =>
          del.mutate(profile.id, {
            onSuccess: () => setConfirmDelete(false),
            onError: (err) => {
              setConfirmDelete(false);
              onError(err);
            },
          })
        }
        title="Xóa profile"
        body={`Xóa "${profile.filename}"? File cấu hình trong profiles_dir cũng bị xóa.`}
        confirmLabel="Xóa"
        destructive
        pending={del.isPending}
      />
    </tr>
  );
}

export function WireGuardPage() {
  const { data, isPending } = useWireGuardOverview();
  const save = useSaveWireGuardSettings();
  const importProfile = useImportWireGuardProfile();
  const discover = useDiscoverProfiles();
  const provision = useProvisionProfile();
  const rotate = useRotateProfile();
  const toast = useToast();

  const [enabled, setEnabled] = useState(false);
  const [profilesDir, setProfilesDir] = useState("");
  const [wgExe, setWgExe] = useState("");
  const [manageService, setManageService] = useState(false);
  const [serviceTimeout, setServiceTimeout] = useState("60");
  const [lockTimeout, setLockTimeout] = useState("30");
  const [wgcfEnabled, setWgcfEnabled] = useState(false);
  const [wgcfExecutable, setWgcfExecutable] = useState("");
  const [wgcfOutput, setWgcfOutput] = useState("");
  const [wgcfTimeout, setWgcfTimeout] = useState("120");
  const [replaceArgv, setReplaceArgv] = useState(false);
  const [wgcfArgv, setWgcfArgv] = useState("");

  const [importName, setImportName] = useState("");
  const [provisionLabel, setProvisionLabel] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!data) return;
    const c = data.config;
    setEnabled(c.enabled);
    setProfilesDir(c.profiles_dir);
    setWgExe(c.wg_exe);
    setManageService(c.manage_service);
    setServiceTimeout(String(c.service_timeout_seconds));
    setLockTimeout(String(c.lock_timeout_seconds));
    setWgcfEnabled(c.wgcf_enabled);
    setWgcfExecutable(c.wgcf_executable);
    setWgcfOutput(c.wgcf_output);
    setWgcfTimeout(String(c.wgcf_timeout_seconds));
    setReplaceArgv(false);
    setWgcfArgv("");
  }, [data]);

  if (isPending || !data) {
    return (
      <Page title="WireGuard">
        <div className="flex items-center justify-center gap-2 py-16 text-sm opacity-60">
          <Spinner /> Đang tải
        </div>
      </Page>
    );
  }

  const submitSettings = () => {
    save.mutate(
      {
        enabled,
        profiles_dir: profilesDir,
        wg_exe: wgExe,
        manage_service: manageService,
        service_timeout_seconds: Number(serviceTimeout) || 0,
        lock_timeout_seconds: Number(lockTimeout) || 0,
        wgcf_enabled: wgcfEnabled,
        wgcf_executable: wgcfExecutable,
        wgcf_output: wgcfOutput,
        wgcf_timeout_seconds: Number(wgcfTimeout) || 0,
        replace_wgcf_argv: replaceArgv,
        wgcf_argv: wgcfArgv,
      },
      {
        onSuccess: () => toast("Đã lưu cấu hình WireGuard toàn cục."),
        onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
      },
    );
  };

  const profiles = data.profiles;

  return (
    <Page
      title="WireGuard"
      hint="Cấu hình toàn cục, ảnh hưởng mọi truyện và mọi thao tác mạng (toc/crawl)"
    >
      <div className="mb-4 rounded-box border border-warning/40 bg-warning/10 px-3.5 py-2.5 text-[13px]">
        Kích hoạt/rotate profile chạy vòng đời tunnel service THẬT của WireGuard for Windows (cần{" "}
        <code>manage_service</code> + quyền admin). Nội dung cấu hình/private key không bao giờ hiển thị hay tải
        về.
      </div>

      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel className="p-4">
          <h3 className="mb-3 text-[13px] font-semibold">Cấu hình toàn cục</h3>
          <div className="space-y-3">
            <label className="flex items-start gap-2 text-[13px]">
              <Checkbox checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="mt-0.5" />
              <span>
                <span className="font-medium">enabled</span>
                <span className="block text-xs opacity-50">Bật scope WireGuard cho thao tác mạng (round-robin xác định).</span>
              </span>
            </label>
            <Field label="profiles_dir" hint="Rỗng = mặc định <db_dir>/wireguard">
              <Input value={profilesDir} onChange={(e) => setProfilesDir(e.target.value)} spellCheck={false} />
            </Field>
            <Field label="wg_exe">
              <Input
                value={wgExe}
                onChange={(e) => setWgExe(e.target.value)}
                placeholder="C:\Program Files\WireGuard\wireguard.exe"
                spellCheck={false}
              />
            </Field>
            <label className="flex items-start gap-2 text-[13px]">
              <Checkbox checked={manageService} onChange={(e) => setManageService(e.target.checked)} className="mt-0.5" />
              <span>
                <span className="font-medium">manage_service</span>
                <span className="block text-xs opacity-50">Tự cài/gỡ tunnel service. Bắt buộc để activate/rotate.</span>
              </span>
            </label>
            <div className="grid grid-cols-2 gap-3">
              <Field label="service_timeout_seconds">
                <Input type="number" step={0.1} value={serviceTimeout} onChange={(e) => setServiceTimeout(e.target.value)} />
              </Field>
              <Field label="lock_timeout_seconds">
                <Input type="number" step={0.1} value={lockTimeout} onChange={(e) => setLockTimeout(e.target.value)} />
              </Field>
            </div>

            <h3 className="pt-2 text-[13px] font-semibold">wgcf (cung cấp profile)</h3>
            <label className="flex items-center gap-2 text-[13px]">
              <Checkbox checked={wgcfEnabled} onChange={(e) => setWgcfEnabled(e.target.checked)} />
              wgcf.enabled
            </label>
            <Field label="wgcf.executable">
              <Input value={wgcfExecutable} onChange={(e) => setWgcfExecutable(e.target.value)} placeholder="C:\tools\wgcf.exe" spellCheck={false} />
            </Field>
            <Field label="wgcf.output">
              <Input value={wgcfOutput} onChange={(e) => setWgcfOutput(e.target.value)} spellCheck={false} />
            </Field>
            <div>
              <p className="mb-1 text-xs opacity-50">
                {data.config.wgcf_argv_configured
                  ? `Đã cấu hình ${data.config.wgcf_argv_count} tham số (giá trị không hiển thị vì có thể chứa token).`
                  : "Chưa cấu hình argv."}
              </p>
              <label className="mb-1.5 flex items-start gap-2 text-[13px]">
                <Checkbox checked={replaceArgv} onChange={(e) => setReplaceArgv(e.target.checked)} className="mt-0.5" />
                <span>
                  <span className="font-medium">replace_wgcf_argv</span>
                  <span className="block text-xs opacity-50">
                    Tích để ghi đè argv bằng nội dung bên dưới — mỗi tham số một dòng, không phải lệnh shell.
                  </span>
                </span>
              </label>
              <Textarea
                value={wgcfArgv}
                onChange={(e) => setWgcfArgv(e.target.value)}
                rows={3}
                disabled={!replaceArgv}
                placeholder={"tham-so-1\ntham-so-2"}
                className="w-full font-mono text-xs"
              />
            </div>
            <Field label="wgcf.timeout_seconds">
              <Input type="number" step={0.1} value={wgcfTimeout} onChange={(e) => setWgcfTimeout(e.target.value)} />
            </Field>

            <Button variant="primary" loading={save.isPending} onClick={submitSettings}>
              Lưu cấu hình
            </Button>
          </div>
        </Panel>

        <Panel className="p-4">
          <h3 className="mb-3 text-[13px] font-semibold">Nhập / quét / cung cấp</h3>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs opacity-70">
              file .conf
              <input ref={fileRef} type="file" accept=".conf,.txt" className="file-input file-input-xs mt-1 block w-48" />
            </label>
            <label className="text-xs opacity-70">
              tên (tuỳ chọn)
              <Input value={importName} onChange={(e) => setImportName(e.target.value)} placeholder="ten-hi-thi" className="mt-1 w-32" />
            </label>
            <Button
              size="sm"
              variant="primary"
              loading={importProfile.isPending}
              onClick={() => {
                const file = fileRef.current?.files?.[0];
                if (!file) {
                  toast("Chưa chọn file.", "error");
                  return;
                }
                importProfile.mutate(
                  { file, name: importName },
                  {
                    onSuccess: () => {
                      toast("Đã nhập profile.");
                      setImportName("");
                      if (fileRef.current) fileRef.current.value = "";
                    },
                    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
                  },
                );
              }}
            >
              Nhập
            </Button>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              size="sm"
              loading={discover.isPending}
              onClick={() =>
                discover.mutate(undefined, {
                  onSuccess: (res) => toast(`Đã quét profiles_dir — thêm ${res.added} profile.`),
                  onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
                })
              }
            >
              Quét thư mục (discover)
            </Button>
            <Input
              value={provisionLabel}
              onChange={(e) => setProvisionLabel(e.target.value)}
              placeholder="warp.conf (nhãn)"
              className="w-36"
            />
            <Button
              size="sm"
              loading={provision.isPending}
              onClick={() =>
                provision.mutate(provisionLabel, {
                  onSuccess: () => {
                    toast("Đã chạy wgcf và nhập profile.");
                    setProvisionLabel("");
                  },
                  onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
                })
              }
            >
              Cung cấp qua wgcf
            </Button>
            <Button
              size="sm"
              loading={rotate.isPending}
              onClick={() =>
                rotate.mutate(undefined, {
                  onSuccess: () => toast("Đã chuyển sang profile kế."),
                  onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
                })
              }
            >
              Rotate
            </Button>
          </div>
        </Panel>
      </div>

      <Panel className="overflow-hidden">
        <PanelHeader title="Profiles" />
        {profiles.length === 0 ? (
          <EmptyState
            title="Chưa có profile nào"
            hint="Nhập file .conf, quét thư mục (discover), hoặc cung cấp qua wgcf."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[52rem] border-collapse text-left">
              <thead>
                <tr className="border-b border-base-300 bg-base-200/60">
                  {["Tên file", "Nguồn", "Trạng thái", "Bật", "Vị trí", ""].map((h) => (
                    <th key={h} className="px-2 py-1.5 text-[10px] font-semibold tracking-[0.1em] uppercase opacity-40">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {profiles.map((p, i) => (
                  <ProfileRow key={p.id} profile={p} isFirst={i === 0} isLast={i === profiles.length - 1} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </Page>
  );
}
