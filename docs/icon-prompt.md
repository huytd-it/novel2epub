# Icon Design Prompt — novel2epub

Prompt dùng để tạo / tái tạo icon cho novel2epub sao cho khớp với design system
hiện tại. Copy nguyên khối dưới, dán vào generator ảnh (Seedream, GPT-Image,
Midjourney, v.v.) hoặc đưa cho designer khi brief.

---

## Prompt (tiếng Anh, ưu tiên)

```
App icon for "novel2epub", a Vietnamese web-novel crawl → translate →
EPUB factory. The brand language is "Xưởng & Trang giấy" (Workshop & Paper
page). Style: minimal flat illustration, one primary subject on a dark
ink-black panel, designed to remain legible at 16×16 px (favicon size).

Composition
- Square 1:1, centered, no text, no border, no gradient background.
- Background: dark ink black (#0e1116) panel with subtle dark rim
  (#242d38), corner radius ≈ 18% of side (squared, "Đông Hồ folk-print
  plaque", not a circle).
- Subject: a single sheet of cream paper (#f7f8f5) with a thin drop
  shadow, placed slightly off-center to leave room for a bookmark
  ribbon on the right.
- On the paper: 3–4 thin horizontal "text" lines in muted brown
  (#a0988a), the last line ~60% width — abstract typography, not real
  characters.
- Right edge: a vertical bookmark ribbon in hoa-hòe gold (#d9a23a)
  extending slightly above the paper, with a notched tail at the bottom.
  The ribbon carries one indigo (#6d8ae0) horizontal band (the
  "source" stage) and one small green (#63b58c) dot (the "reviewer
  approved" stage).
- Below the paper, inside the dark panel, a thin rounded progress bar
  ~62% filled with a left-to-right gradient from indigo (#6d8ae0) to
  green (#63b58c) — the "chapters done" count.

Color tokens (must match frontend/src/styles/theme.css)
- base-200  #0e1116  panel background
- base-100  #151a21  panel inset
- base-300  #242d38  rim
- base-100 light  #f7f8f5  paper
- primary  #d9a23a  gold (ribbon, "machine" stage)
- secondary #6d8ae0 indigo (source)
- accent   #63b58c green (reviewer)
- error    #e0664a cinnabar (must NOT appear in the icon — reserved
           for failure state only)
- text-line #a0988a muted brown (abstract "text" lines on paper)

Constraints
- No emoji, no realistic illustration, no photographic paper texture,
  no drop shadow beyond a single 1px offset.
- Stroke weight ≤ 4% of side; details thinner than 1px must be dropped
  at 32×32 to stay readable.
- The icon must read at 16×16 as: dark square with a gold vertical
  stripe and a faint cream rectangle — that is the minimum legible
  silhouette.
- The maskable variant (used on Android adaptive icons) must keep the
  paper and ribbon centered inside a 12% safe-zone from every edge;
  the progress bar is removed in the maskable version.
- Do not introduce new colors. If a value is missing from the token
  list above, do not invent it — request the token from the design
  system owner.

Deliverables (PNG + ICO, transparent where noted)
- favicon.ico           multi-size 16/32/48, transparent not required
- icon-16.png           transparent
- icon-32.png           transparent
- icon-48.png           transparent
- icon-64.png           transparent
- icon-128.png          transparent
- icon-192.png          transparent  (PWA + apple-touch-icon source)
- icon-256.png          transparent
- icon-512.png          transparent  (PWA + tauri source)
- maskable-512.png      opaque dark panel, safe-zone 12%
```

## Prompt (tiếng Việt, dùng khi generator ưu tiên tiếng Việt)

```
Icon app "novel2epub" — xưởng crawl, dịch và đóng gói EPUB tiếng Việt.
Ngôn ngữ thương hiệu: "Xưởng & Trang giấy". Phong cách: min flat, một
chủ thể chính trên panel đen mực, phải đọc rõ ở 16×16 px (favicon).

Bố cục
- Vuông 1:1, căn giữa, không chữ, không viền ngoài, không nền gradient.
- Nền: panel đen mực (#0e1116) với viền mờ (#242d38), bo góc ≈ 18%
  cạnh (vuông vắn, kiểu khuôn tranh Đông Hồ, không bo tròn).
- Chủ thể: một tờ giấy kem (#f7f8f5) với bóng đổ mỏng, đặt lệch trái
  để chừa chỗ cho bookmark bên phải.
- Trên giấy: 3–4 dòng ngang mảnh màu nâu nhạt (#a0988a), dòng cuối
  ngắn ~60% — gợi chữ nhưng không phải ký tự thật.
- Mép phải: bookmark dọc màu vàng hoa hòe (#d9a23a) nhô lên khỏi mép
  trên, đuôi xẻ vát. Trên ribbon có một vạch chàm ngang (#6d8ae0) —
  giai đoạn "nguồn" — và một chấm lục nhỏ (#63b58c) — "người duyệt
  đã xong".
- Dưới giấy, trong panel đen, một thanh tiến độ mỏng bo góc fill ~62%
  gradient từ chàm (#6d8ae0) sang lục (#63b58c) — gợi "số chương đã
  xong".

Token màu (phải khớp frontend/src/styles/theme.css)
- base-200  #0e1116  nền panel
- base-100  #151a21  panel inset
- base-300  #242d38  viền
- base-100 light  #f7f8f5  giấy
- primary  #d9a23a  vàng (ribbon, "máy")
- secondary #6d8ae0 chàm (nguồn)
- accent   #63b58c lục (người duyệt)
- error    #e0664a son — KHÔNG dùng trong icon, chỉ dành cho trạng
           thái lỗi
- text-line #a0988a nâu nhạt (dòng chữ trên giấy)

Ràng buộc
- Không emoji, không minh họa hiện thực, không texture giấy chụp, chỉ
  một bóng đổ lệch 1px.
- Nét stroke ≤ 4% cạnh; chi tiết mỏng hơn 1px phải lược bỏ ở 32×32.
- Ở 16×16 đọc được: ô vuông tối có một vạch vàng dọc và một hình
  chữ nhật kem mờ — đó là hình silhouette tối thiểu.
- Bản maskable (Android adaptive) phải giữ giấy và ribbon căn giữa
  trong safe-zone 12% từ mọi cạnh; thanh tiến độ được lược bỏ.
- Không tự ý thêm màu mới. Thiếu token thì hỏi lại người giữ design
  system.

Output (PNG + ICO, trong suốt trừ khi ghi chú)
- favicon.ico           multi-size 16/32/48
- icon-{16,32,48,64,128,192,256,512}.png  trong suốt
- maskable-512.png      panel tối đặc, safe-zone 12%
```

## Quy trình tạo icon mới

1. Chạy prompt ở trên để có ảnh gốc 512×512.
2. Sinh đủ các size bằng `Pillow` (LANCZOS). Lệnh nhanh:

   ```python
   from PIL import Image
   sizes = [16, 32, 48, 64, 128, 192, 256, 512]
   src = Image.open("icon-512.png")
   for s in sizes:
       src.resize((s, s), Image.LANCZOS).save(f"icon-{s}.png")
   ```

3. Gói `favicon.ico` đa kích thước (16/32/48).
4. Làm `maskable-512.png`: bỏ progress bar, căn giữa giấy + ribbon
   trong safe-zone 12%, nền panel đặc `#0e1116`.
5. Bỏ vào `app/webui/icons/`. `index.html` đã có sẵn các thẻ
   `<link rel="icon">` 16/32 và `apple-touch-icon` 192; nếu thêm size
   mới thì cập nhật thẻ tương ứng trong `app/webui/index.html`.
6. Build lại frontend: `cd frontend && npm run build` để `vite-plugin-pwa`
   precache asset mới.

## Lưu ý

- Không commit ảnh vào repo nếu `app/webui/` đã nằm trong `.gitignore`
  (đúng với repo này: build artifact). Chỉ commit nếu ảnh là asset
  tĩnh đi kèm source frontend.
- Khi đổi palette, cập nhật cả `frontend/src/styles/theme.css` lẫn
  file prompt này — hai nguồn phải khớp từng token.
