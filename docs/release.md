# Release Và Triển Khai

## Luồng tự động

- Pull request và `main`: `.github/workflows/ci.yml` kiểm tra backend API, TypeScript và web build.
- Push tag `v*`: `.github/workflows/release.yml` tạo GitHub Release cho Windows, macOS và Linux; Android/iOS được khởi tạo trong runner và build artifact unsigned.
- Push `main`: `.github/workflows/deploy-vercel.yml` deploy production lên Vercel.

Version của tag nên khớp `frontend/package.json`, `frontend/src-tauri/tauri.conf.json` và `frontend/src-tauri/Cargo.toml`.

## GitHub secrets và variables

Vercel Environment `production` cần:

- `VERCEL_TOKEN`
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID`
- Variable `N2E_API_BASE`: URL HTTPS mặc định của backend, ví dụ hostname `.ts.net` hoặc Funnel. Đây là URL công khai trong bundle, không phải secret.

Không đưa API token novel2epub vào GitHub variable, Vercel environment hoặc JavaScript bundle. Người dùng nhập token tại trang **Kết nối**; token được lưu cục bộ trên thiết bị.

Các artifact mobile hiện unsigned. Để phát hành store cần bổ sung Android keystore và Apple certificate/provisioning/App Store Connect credentials vào GitHub Environment có approval. Không commit khóa, provisioning profile hay service-account JSON.

## Tailscale riêng

Chạy FastAPI chỉ trên loopback rồi dùng Tailscale Serve:

```sh
uvicorn app.main:app --host 127.0.0.1 --port 8010
tailscale serve --bg https / http://127.0.0.1:8010
```

Dùng URL được Tailscale cấp, ví dụ `https://may-chu.tailnet.ts.net`. Thiết bị mở frontend Vercel phải đăng nhập cùng tailnet. Cấu hình token API mạnh và thêm chính xác origin Vercel vào `api.cors_origins`.

## Tailscale Funnel

Funnel phù hợp khi thiết bị client không tham gia tailnet:

```sh
tailscale funnel --bg https / http://127.0.0.1:8010
```

Funnel công khai backend ra Internet. Bắt buộc:

- token API ngẫu nhiên mạnh;
- HTTPS;
- CORS chỉ chứa domain Vercel thực tế, không dùng `*`;
- Tailscale ACL và rate limiting/reverse proxy nếu endpoint chịu tải công khai;
- không expose SQLite, log, API key dịch hoặc Supabase service-role key.

Tắt Funnel khi không cần:

```sh
tailscale funnel reset
```

## Vercel

`vercel.json` giữ ứng dụng tại `/app/`, redirect `/` sang `/app/` và rewrite deep link React Router về SPA entrypoint. Link project một lần để lấy Org/Project ID, sau đó lưu ba Vercel secrets trong GitHub.

## Mobile

Generated projects dưới `frontend/src-tauri/gen/` được tạo mới trong CI bằng Tauri CLI. Android job tạo APK/AAB unsigned. iOS cần macOS/Xcode; unsigned `.app`/archive chỉ dùng kiểm thử và không cài lên thiết bị production như bản App Store.
