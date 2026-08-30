import { useEffect, useMemo, useState } from "react";
import { QRCodeSVG } from "qrcode.react";

import { Page } from "@/app/Shell";
import {
  useTailscaleStatus,
  useTailscaleConfig,
  useSaveTailscaleConfig,
  useServeEnable,
  useFunnelEnable,
  useServeReset,
  useFunnelReset,
  useTailscaleDisable,
} from "@/lib/tailscale";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Field, Input, Checkbox } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return <Badge tone={ok ? "celadon" : "vermilion"}>{label}</Badge>;
}

export function TailscalePage() {
  const toast = useToast();
  const statusQ = useTailscaleStatus();
  const configQ = useTailscaleConfig();
  const save = useSaveTailscaleConfig();
  const serveOn = useServeEnable();
  const funnelOn = useFunnelEnable();
  const serveOff = useServeReset();
  const funnelOff = useFunnelReset();
  const disableAll = useTailscaleDisable();

  const [binary, setBinary] = useState("tailscale");
  const [port, setPort] = useState("8010");
  const [servePath, setServePath] = useState("/");
  const [target, setTarget] = useState("");
  const [useHttps, setUseHttps] = useState(true);
  const [timeout, setTimeout] = useState("15");

  useEffect(() => {
    if (!configQ.data) return;
    setBinary(configQ.data.binary);
    setPort(String(configQ.data.port));
    setServePath(configQ.data.serve_path);
    setTarget(configQ.data.target);
    setUseHttps(configQ.data.use_https);
    setTimeout(String(configQ.data.timeout_seconds));
  }, [configQ.data]);

  const overview = statusQ.data;
  const cfg = configQ.data;

  const serveUrl = useMemo(() => {
    if (!overview?.self_dns || !overview?.status_ok) return null;
    const host = overview.self_dns.replace(/\/+$/, "");
    if (!host) return null;
    const rawPath = (cfg?.serve_path || "/").trim() || "/";
    const path = rawPath.startsWith("/") ? rawPath : `/${rawPath}`;
    const cleanPath = path === "/" ? "" : path;
    return `https://${host}${cleanPath}`;
  }, [overview, cfg]);
  const isServeActive = Boolean(overview?.serve?.on || overview?.serve?.funnel_on);

  const windowPort = useMemo(() => {
    try {
      const p = window.location.port;
      return p ? Number(p) : null;
    } catch {
      return null;
    }
  }, []);
  const portMismatch = useMemo(() => {
    if (!cfg?.port || !windowPort) return false;
    // Chỉ cảnh báo khi đang truy cập qua localhost/127.0.0.1 (biết chắc cổng local)
    const host = window.location.hostname;
    const isLocal = host === "127.0.0.1" || host === "localhost" || host === "::1";
    return isLocal && cfg.port !== windowPort;
  }, [cfg?.port, windowPort]);

  const [checkState, setCheckState] = useState<"idle" | "checking" | "ok" | "err">("idle");
  const [checkMsg, setCheckMsg] = useState("");

  const checkServeUrl = async () => {
    if (!serveUrl) return;
    setCheckState("checking");
    setCheckMsg("");
    try {
      // Dùng no-cors không đọc được status, nên fetch với cors. Nếu 502 sẽ trả lỗi.
      const res = await fetch(serveUrl, { method: "GET", cache: "no-store" });
      if (res.ok) {
        setCheckState("ok");
        setCheckMsg(`OK ${res.status}`);
        toast("Liên kết hoạt động.");
      } else if (res.status === 502) {
        setCheckState("err");
        setCheckMsg("502 Bad Gateway — backend không phản hồi. Kiểm tra Port Web UI khớp cổng uvicorn (xem cảnh báo cổng).");
        toast("502 — backend không phản hồi, kiểm tra cổng.", "error");
      } else {
        setCheckState("err");
        setCheckMsg(`HTTP ${res.status} ${res.statusText}`);
      }
    } catch (e) {
      setCheckState("err");
      setCheckMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const serveTargets = useMemo(() => {
    const cfgRaw = overview?.serve.config as unknown as Record<string, unknown> | null;
    if (!cfgRaw) return [];
    const found: string[] = [];
    const search = (obj: unknown) => {
      if (typeof obj === "string" && obj.includes("127.0.0.1")) found.push(obj);
      if (obj && typeof obj === "object") Object.values(obj as Record<string, unknown>).forEach(search);
    };
    search(cfgRaw);
    // Nếu raw chứa ServeConfig dạng khác, thử raw
    if (found.length === 0 && overview?.serve.raw) search(overview.serve.raw);
    return [...new Set(found)];
  }, [overview]);

  const onSave = () => {
    save.mutate(
      {
        binary: binary.trim() || "tailscale",
        port: Number(port) || 8010,
        serve_path: servePath.trim() || "/",
        target: target.trim(),
        use_https: useHttps,
        timeout_seconds: Number(timeout) || 15,
      },
      {
        onSuccess: () => toast("Đã lưu cấu hình Tailscale."),
        onError: (e) => toast(e instanceof Error ? e.message : String(e), "error"),
      },
    );
  };

  const handle = (
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- các hook có chữ ký mutate khác nhau (void vs record)
    mut: { mutate: (v: any, o: { onSuccess?: () => void; onError?: (e: unknown) => void }) => void; isPending: boolean },
    label: string,
    payload?: Record<string, unknown>,
  ) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (mut.mutate as any)(payload, {
      onSuccess: () => toast(label),
      onError: (e: unknown) => toast(e instanceof Error ? e.message : String(e), "error"),
    });
  };

  if (statusQ.isPending || configQ.isPending) {
    return (
      <Page title="Tailscale" loading>
        {null}
      </Page>
    );
  }

  return (
    <Page
      title="Tailscale"
      hint="Mở cổng Web UI ra tailnet (Serve) hoặc Internet (Funnel) — quản lý tailscale serve/funnel ngay trong Web UI"
      actions={
        <Button size="sm" onClick={() => statusQ.refetch()} loading={statusQ.isFetching}>
          Làm mới trạng thái
        </Button>
      }
    >
      {/* Cảnh báo Funnel */}
      <div className="mb-4 rounded-box border border-warning/40 bg-warning/10 px-3.5 py-2.5 text-[13px]">
        <strong>Funnel</strong> mở Web UI ra Internet công cộng — chỉ bật khi đã đặt token API mạnh, HTTPS và CORS đúng origin.
        <span className="opacity-70"> Serve </span> chỉ cho thiết bị trong tailnet mới vào được (khuyên dùng).
      </div>

      {portMismatch ? (
        <div className="mb-4 rounded-box border border-error/40 bg-error/10 px-3.5 py-3 text-[13px]">
          <strong className="text-error">Cảnh báo cổng không khớp — có thể gây 502</strong>
          <p className="mt-1 opacity-80">
            Bạn đang mở Web UI tại <code>:{windowPort}</code> nhưng cấu hình Tailscale đang để <code>:{cfg?.port}</code>.
            Tailscale sẽ forward tới <code>http://127.0.0.1:{cfg?.port}</code> và trả 502 nếu cổng sai.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" variant="primary" onClick={() => setPort(String(windowPort))}>
              Đổi Port thành {windowPort}
            </Button>
            <span className="self-center text-xs opacity-60">→ rồi bấm “Lưu cấu hình” và “Bật Serve” lại</span>
          </div>
        </div>
      ) : null}

      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Trạng thái */}
        <Panel className="p-4">
          <h3 className="mb-3 text-[13px] font-semibold">Trạng thái</h3>
          {overview ? (
            <div className="space-y-2 text-[13px]">
              <div className="flex flex-wrap items-center gap-2">
                <span className="opacity-60">Tailscale:</span>
                <code className="text-xs">{overview.binary}</code>
                {overview.version ? <Badge tone="neutral">{overview.version}</Badge> : null}
                <StatusBadge ok={overview.status_ok} label={overview.status_ok ? "running" : "lỗi"} />
                {overview.backend_state ? <span className="text-xs opacity-60">({overview.backend_state})</span> : null}
              </div>
              {overview.status_ok ? (
                <>
                  <p>
                    <span className="opacity-60">Tailnet:</span> <code className="text-xs">{overview.tailnet || "(chưa rõ)"}</code>
                    {overview.self_dns ? (
                      <>
                        {" "}
                        · <span className="opacity-60">Self DNS:</span> <code className="text-xs">{overview.self_dns}</code>
                      </>
                    ) : null}
                    {overview.self_ip ? (
                      <>
                        {" "}
                        · <span className="opacity-60">IP:</span> <code className="text-xs">{overview.self_ip}</code>
                      </>
                    ) : null}
                  </p>
                </>
              ) : (
                <p className="text-xs text-error">{overview.status_error || "Không lấy được trạng thái — kiểm tra tailscaled đã chạy và đã login chưa."}</p>
              )}

              <div className="flex flex-wrap items-center gap-2 pt-2">
                <span className="opacity-60">Serve:</span>
                <StatusBadge ok={overview.serve.on} label={overview.serve.on ? "đang mở" : "tắt"} />
                <span className="opacity-60">Funnel:</span>
                <StatusBadge ok={overview.serve.funnel_on} label={overview.serve.funnel_on ? "đang mở" : "tắt"} />
              </div>

              {serveTargets.length > 0 ? (
                <p className="text-xs opacity-70">
                  Forward tới: {serveTargets.map((t) => <code key={t} className="mr-1 rounded bg-base-200 px-1">{t}</code>)}
                </p>
              ) : isServeActive ? (
                <p className="text-xs text-warning">Serve đang mở nhưng không dò được target — kiểm tra “Xem JSON ServeConfig”.</p>
              ) : null}
              {isServeActive && serveTargets.length > 0 && cfg && !serveTargets.some((t) => t.includes(`:${cfg.port}`)) ? (
                <p className="text-xs text-error">
                  Target {serveTargets.join(", ")} không khớp Port Web UI :{cfg.port} — chắc chắn 502! Sửa Port rồi “Bật Serve” lại.
                </p>
              ) : null}

              {/* Hiển thị URL suy ra nếu có */}
              {overview.self_dns ? (
                <p className="text-xs opacity-60">
                  URL dự kiến (Serve): <code>https://{overview.self_dns}</code> (cần Serve đang bật)
                </p>
              ) : null}

              {overview.serve.config ? (
                <details className="rounded-box border border-base-300 bg-base-200/40 p-2">
                  <summary className="cursor-pointer text-xs font-medium">Xem JSON ServeConfig</summary>
                  <pre className="mt-2 max-h-64 overflow-auto text-[11px] leading-4">{JSON.stringify(overview.serve.config, null, 2)}</pre>
                </details>
              ) : null}
              {overview.serve.raw && !overview.serve.config ? (
                <details className="rounded-box border border-base-300 bg-base-200/40 p-2">
                  <summary className="cursor-pointer text-xs font-medium">Xem JSON raw (serve status)</summary>
                  <pre className="mt-2 max-h-64 overflow-auto text-[11px] leading-4">{JSON.stringify(overview.serve.raw, null, 2)}</pre>
                </details>
              ) : null}
            </div>
          ) : (
            <p className="text-xs opacity-60">Không lấy được trạng thái.</p>
          )}

          <div className="mt-4 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="primary"
              loading={serveOn.isPending}
              onClick={() => handle(serveOn, "Đã bật Tailscale Serve (tailnet).")}
            >
              Bật Serve (tailnet)
            </Button>
            <Button
              size="sm"
              variant="primary"
              loading={funnelOn.isPending}
              onClick={() => handle(funnelOn, "Đã bật Tailscale Funnel (công khai).")}
            >
              Bật Funnel (public)
            </Button>
            <Button size="sm" loading={serveOff.isPending} onClick={() => handle(serveOff, "Đã tắt Serve.")}>
              Tắt Serve
            </Button>
            <Button size="sm" loading={funnelOff.isPending} onClick={() => handle(funnelOff, "Đã tắt Funnel.")}>
              Tắt Funnel
            </Button>
            <Button
              size="sm"
              variant="danger"
              loading={disableAll.isPending}
              onClick={() => handle(disableAll, "Đã tắt toàn bộ Serve/Funnel.")}
            >
              Tắt hết
            </Button>
          </div>
          <p className="mt-2 text-xs opacity-50">
            Mặc định dùng cổng <code>{cfg?.port ?? 8010}</code> và target <code>{cfg?.target || `http://127.0.0.1:${cfg?.port ?? 8010}`}</code>. Đổi trong “Cấu hình” bên phải rồi bấm Bật lại.
          </p>
        </Panel>

        {/* Cấu hình */}
        <Panel className="p-4">
          <h3 className="mb-3 text-[13px] font-semibold">Cấu hình</h3>
          <div className="space-y-3">
            <Field label="Binary" hint="Mặc định 'tailscale' trong PATH">
              <Input value={binary} onChange={(e) => setBinary(e.target.value)} placeholder="tailscale" spellCheck={false} />
            </Field>
            <Field label="Port Web UI" hint="Cổng uvicorn đang chạy (mặc định 8010)">
              <Input type="number" value={port} onChange={(e) => setPort(e.target.value)} />
            </Field>
            <Field label="Target" hint="Rỗng = http://127.0.0.1:<port>">
              <Input value={target} onChange={(e) => setTarget(e.target.value)} placeholder="http://127.0.0.1:8010" spellCheck={false} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Serve path">
                <Input value={servePath} onChange={(e) => setServePath(e.target.value)} placeholder="/" spellCheck={false} />
              </Field>
              <Field label="Timeout (giây)">
                <Input type="number" step={0.1} value={timeout} onChange={(e) => setTimeout(e.target.value)} />
              </Field>
            </div>
            <label className="flex items-center gap-2 text-[13px]">
              <Checkbox checked={useHttps} onChange={(e) => setUseHttps(e.target.checked)} />
              use_https (https /)
            </label>
            <Button variant="primary" loading={save.isPending} onClick={onSave}>
              Lưu cấu hình
            </Button>
          </div>
        </Panel>
      </div>

      {/* Link & QR — chỉ hiện khi đã có self_dns và tailscaled chạy */}
      <Panel className="overflow-hidden">
        <PanelHeader
          title="Liên kết & mã QR"
          hint={isServeActive ? "Quét mã để mở Web UI trên điện thoại (phải trong cùng tailnet nếu dùng Serve)" : "Bật Serve/Funnel để lấy liên kết"}
        />
        <div className="p-4">
          {!overview?.status_ok ? (
            <p className="text-sm opacity-60">Tailscaled chưa chạy hoặc chưa login — không có liên kết.</p>
          ) : !serveUrl ? (
            <p className="text-sm opacity-60">Chưa có Self DNS (đợi tailscale up và MagicDNS). Thử “Làm mới trạng thái”.</p>
          ) : (
            <div className="flex flex-col gap-4 md:flex-row md:items-start">
              <div className="min-w-0 flex-1 space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <code className="break-all rounded bg-base-200 px-2 py-1 text-sm">{serveUrl}</code>
                  <Badge tone={isServeActive ? "celadon" : "gold"}>{isServeActive ? (overview?.serve.funnel_on ? "Funnel đang mở (public)" : "Serve đang mở (tailnet)") : "Chưa mở"}</Badge>
                </div>
                <p className="text-xs opacity-60">
                  {isServeActive
                    ? overview?.serve.funnel_on
                      ? "Bất kỳ ai có link đều vào được (public Internet). Đảm bảo token API mạnh + CORS đúng."
                      : "Chỉ thiết bị trong cùng tailnet mới mở được link này."
                    : "Bấm “Bật Serve” ở trên để tailscale cấp URL, sau đó link và QR sẽ khả dụng."}
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="primary"
                    disabled={!isServeActive}
                    onClick={() => window.open(serveUrl, "_blank", "noopener,noreferrer")}
                  >
                    Mở liên kết
                  </Button>
                  <Button
                    size="sm"
                    disabled={!serveUrl}
                    onClick={async () => {
                      try {
                        if (navigator.clipboard?.writeText) {
                          await navigator.clipboard.writeText(serveUrl);
                        } else {
                          const ta = document.createElement("textarea");
                          ta.value = serveUrl;
                          document.body.appendChild(ta);
                          ta.select();
                          document.execCommand("copy");
                          ta.remove();
                        }
                        toast("Đã sao chép liên kết.");
                      } catch {
                        toast("Không sao chép được.", "error");
                      }
                    }}
                  >
                    Sao chép
                  </Button>
                  <a
                    href={serveUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn btn-sm btn-ghost"
                  >
                    Mở trong tab mới ↗
                  </a>
                  <Button size="sm" variant="ghost" loading={checkState === "checking"} disabled={!isServeActive} onClick={checkServeUrl}>
                    Kiểm tra
                  </Button>
                </div>
                {checkState !== "idle" ? (
                  <p className={`text-xs ${checkState === "ok" ? "text-success" : checkState === "checking" ? "opacity-60" : "text-error"}`}>{checkMsg || (checkState === "checking" ? "Đang kiểm tra..." : "")}</p>
                ) : null}
                {isServeActive && overview?.self_ip ? (
                  <p className="text-xs opacity-50">
                    IP trực tiếp (fallback): <code>http://{overview.self_ip}:{cfg?.port ?? 8010}</code>
                  </p>
                ) : null}
              </div>

              <div className="flex flex-col items-center gap-2">
                <div id="tailscale-qr" className="rounded-box border border-base-300 bg-white p-3 shadow-sm">
                  <QRCodeSVG
                    value={serveUrl}
                    size={168}
                    level="M"
                    bgColor="#ffffff"
                    fgColor="#111827"
                    marginSize={1}
                  />
                </div>
                <span className="text-xs opacity-50">Quét bằng camera điện thoại</span>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    const svg = document.querySelector("#tailscale-qr svg") as unknown as HTMLElement;
                    if (!svg) return;
                    const data = new XMLSerializer().serializeToString(svg);
                    const blob = new Blob([data], { type: "image/svg+xml" });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = "tailscale-qr.svg";
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                >
                  Tải QR (.svg)
                </Button>
              </div>
            </div>
          )}
        </div>
      </Panel>

      <Panel className="overflow-hidden">
        <PanelHeader title="Hướng dẫn nhanh" />
        <div className="p-4 text-[13px] leading-relaxed">
          <ol className="list-decimal space-y-1 pl-5">
            <li>
              Chạy backend: <code>uvicorn app.main:app --host 127.0.0.1 --port {cfg?.port ?? 8010}</code> (chỉ loopback).
            </li>
            <li>
              Bấm <strong>Bật Serve</strong> ở trên — tương đương <code>tailscale serve --bg {cfg?.port ?? 8010}</code>. Kiểm tra URL{" "}
              <code>https://&lt;máy&gt;.&lt;tailnet&gt;.ts.net</code> trên thiết bị khác trong cùng tailnet.
            </li>
            <li>
              Nếu cần công khai ra Internet cho thiết bị ngoài tailnet: bấm <strong>Bật Funnel</strong> (tương đương{" "}
              <code>tailscale funnel --bg {cfg?.port ?? 8010}</code>). Bắt buộc token API mạnh + CORS chỉ chứa origin Vercel thực tế.
            </li>
            <li>
              Tắt khi không dùng: <strong>Tắt hết</strong> (tương đương <code>tailscale serve reset</code>).
            </li>
          </ol>
          <p className="mt-3 text-xs opacity-60">
            Lưu ý: <code>tailscaled</code> phải đang chạy và đã <code>tailscale up</code> / login trước. Nếu status báo lỗi, mở terminal chạy{" "}
            <code>tailscale status</code> để xem chi tiết. Web UI không tự cài tailscale — chỉ điều khiển serve/funnel khi binary đã có.
          </p>
          <details className="mt-3 rounded-box border border-base-300 bg-base-200/40 p-3">
            <summary className="cursor-pointer text-xs font-semibold">Gặp 502 Bad Gateway?</summary>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-xs opacity-80">
              <li>
                Kiểm tra backend có đang lắng nghe <code>http://127.0.0.1:{cfg?.port ?? 8010}</code> không — chạy <code>curl http://127.0.0.1:{cfg?.port ?? 8010}/api/tailscale/status</code> trên máy host phải trả 200.
              </li>
              <li>
                Port trong “Cấu hình” phải khớp cổng <code>uvicorn --port</code> bạn đang chạy (bạn đang ở <code>{windowPort ?? "?"}</code>). Không khớp → 502. Sửa Port, “Lưu cấu hình”, “Tắt hết”, rồi “Bật Serve” lại.
              </li>
              <li>
                Xem “Forward tới” ở trên — nếu không khớp cổng, reset và bật lại.
              </li>
              <li>
                Thử <code>tailscale serve status --json</code> trong terminal để xem ServeConfig thực tế.
              </li>
              <li>
                Nếu vẫn 502, chạy <code>tailscale serve reset</code> rồi bật lại, hoặc kiểm tra firewall/antivirus chặn loopback.
              </li>
            </ul>
          </details>
        </div>
      </Panel>
    </Page>
  );
}
