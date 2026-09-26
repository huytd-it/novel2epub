"""Đồng bộ preset giữa DB (nguồn sự thật) và file YAML `sources.yaml`.

Vì sao cần: preset nằm trong DB nhưng nhiều người vẫn giữ `sources.yaml` cạnh
DB làm file cấu hình/backup. Hai bên sẽ trôi lệch nhau — hoặc vì sửa trong UI,
hoặc vì tay sửa file. Module này làm 3 việc, đều thuần và test được:

1. `read_sources_file` — đọc + chuẩn hoá file (chấp nhận cả dạng phẳng của
   `sources.yaml` cũ lẫn dạng bọc `sources:` của file export).
2. `plan_sync` — so file với DB, ra diff từng preset + field và gợi ý hành
   động mặc định để UI xem trước.
3. `apply_sync` — thi hành lựa chọn của người dùng, ghi DB, rồi ghi ngược file
   (có backup, ghi atomic).

Hợp đồng (cố ý tường minh, không suy diễn):

- `import` — bản trong FILE thắng: ghi vào DB, file giữ nguyên bản đó.
- `export` — bản trong DB thắng: file được ghi bằng bản của DB, DB không đổi.
- `skip`   — không đụng gì cả hai bên; entry trong file giữ nguyên từng ký tự.

Sau khi sync, file là ảnh chụp của DB (trừ preset bị `skip`), nên "import" với
preset chỉ khác ở field DB không sửa là một no-op — đó là hệ quả đúng của "đã đồng
bộ", không phải lỗi: giá trị của nó là preset chỉ có ở một bên được gom về một
chỗ và file thành backup thật.
"""
from __future__ import annotations

import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from .sources import (
    PRESET_FIELD_NAMES,
    SourcePreset,
    load_presets,
    preset_from_mapping,
    save_preset,
)

FLAT = "flat"
WRAPPED = "wrapped"

DEFAULT_FILENAME = "sources.yaml"
ALLOWED_SUFFIXES = {".yaml", ".yml"}

IMPORT = "import"
EXPORT = "export"
SKIP = "skip"

Action = Literal["import", "export", "skip"]
Status = Literal["added", "db_only", "changed", "same"]

ACTION_LABELS = {
    IMPORT: "Lấy từ file → DB",
    EXPORT: "Lấy từ DB → file",
    SKIP: "Bỏ qua",
}


class SyncError(ValueError):
    """Lỗi nghiệp vụ khi sync — message tiếng Việt để hiện thẳng lên UI."""


# ── đọc file ────────────────────────────────────────────────────────────

def default_path(db_path: str | Path) -> Path:
    """`sources.yaml` nằm cạnh file DB — vị trí mặc định của nút Sync."""
    return Path(db_path).resolve().parent / DEFAULT_FILENAME


def resolve_path(db_path: str | Path, raw: str = "") -> Path:
    """Đường dẫn tương đối được hiểu là cạnh DB (nơi `sources.yaml` vốn nằm)."""
    raw = (raw or "").strip()
    path = Path(raw) if raw else default_path(db_path)
    if not path.is_absolute():
        path = Path(db_path).resolve().parent / path
    path = path.resolve()
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise SyncError(f"File phải có đuồi {', '.join(sorted(ALLOWED_SUFFIXES))} (đang là '{path.suffix or 'không có'}').")
    return path


def read_sources_file(path: str | Path) -> tuple[str, dict[str, SourcePreset], list[str]]:
    """Đọc file preset. Trả `(layout, presets, warnings)`.

    `layout` là `wrapped` (có khoá `sources:`) hay `flat` (mapping preset ở cấp
    cao nhất — dạng của `sources.yaml` cũ). File không tồn tại → `({}, warnings)`
    với layout mặc định `flat`; khi đó caller coi như "chỉ có DB".
    """
    path = Path(path)
    warnings: list[str] = []
    if not path.exists():
        return FLAT, {}, [f"Không có file {path.name} — sẽ tạo mới từ preset trong DB."]
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise SyncError(f"Không đọc được {path.name}: {e}") from e
    if raw is None:
        return FLAT, {}, [f"{path.name} rỗng."]
    if not isinstance(raw, dict):
        raise SyncError(
            f"{path.name} phải là mapping YAML, đang là {type(raw).__name__}."
        )

    if isinstance(raw.get("sources"), dict):
        layout, incoming = WRAPPED, raw["sources"]
    else:
        # Dạng phẳng: MỌI khoá cấp cao nhất phải là một preset. Block preset phải
        # chứa ít nhất một field quen — đây là cách phân biệt với file gộp cấu
        # hình (`defaults:`, `ebooks:`, `queue:`... vốn cũng là dict).
        suspect = [
            k for k, v in raw.items()
            if v and (not isinstance(v, dict) or not (set(v) & PRESET_FIELD_NAMES))
        ]
        if suspect:
            raise SyncError(
                f"{path.name} không phải file nguồn: các khoá không giống preset "
                f"({', '.join(map(str, suspect[:5]))}). File đúng phải là mapping "
                "preset ở cấp cao nhất, hoặc có khoá `sources:`."
            )
        layout, incoming = FLAT, raw

    presets: dict[str, SourcePreset] = {}
    for name, item in incoming.items():
        if item is None:
            item = {}
        if not isinstance(item, dict):
            raise SyncError(f"Preset '{name}' trong {path.name} phải là mapping, đang là {type(item).__name__}.")
        presets[str(name)] = preset_from_mapping(str(name), item)

    unknown = [
        k for k, v in incoming.items()
        if isinstance(v, dict) and any(key not in PRESET_FIELD_NAMES for key in v)
    ]
    if unknown:
        warnings.append(
            "Bỏ qua field không quen trong preset: "
            + ", ".join(f"{n}.{key}" for n in unknown[:3] for key in list(incoming[n])[:4])
        )
    return layout, presets, warnings


# ── diff ────────────────────────────────────────────────────────────────

@dataclass
class FieldDiff:
    key: str
    file_value: Any
    db_value: Any


@dataclass
class PresetDiff:
    name: str
    status: Status
    action: Action
    actions: list[Action]
    fields: list[FieldDiff] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "action": self.action,
            "actions": self.actions,
            "fields": [vars(f) for f in self.fields],
        }


@dataclass
class SyncPlan:
    path: str
    layout: str
    exists: bool
    file_order: list[str]
    diffs: list[PresetDiff]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "layout": self.layout,
            "exists": self.exists,
            "file_order": self.file_order,
            "presets": [d.to_dict() for d in self.diffs],
            "warnings": self.warnings,
            "counts": {
                status: sum(1 for d in self.diffs if d.status == status)
                for status in ("added", "changed", "db_only", "same")
            },
        }


def _comparable(preset: SourcePreset) -> dict[str, Any]:
    return {k: v for k, v in asdict(preset).items() if k != "name"}


def _valid_actions(status: Status) -> list[Action]:
    if status == "added":       # chỉ có trong file → chỉ có thể import
        return [IMPORT, SKIP]
    if status == "db_only":     # chỉ có trong DB → chỉ có thể đẩy ra file
        return [EXPORT, SKIP]
    if status == "changed":     # hai bên khác nhau → người dùng chọn bên thắng
        return [IMPORT, EXPORT, SKIP]
    return [SKIP]               # giống hệt → không có gì để quyết


def plan_sync(
    db_path: str | Path,
    path: str | Path,
    file_presets: dict[str, SourcePreset],
    layout: str = FLAT,
    file_order: list[str] | None = None,
    warnings: list[str] | None = None,
) -> SyncPlan:
    """So preset trong DB với preset trong file, ra kế hoạch sync.

    Hàm thuần — không đọc/ghi gì; `file_presets` do `read_sources_file` trả về
    (route sẽ gọi cả hai).
    """
    db_presets = load_presets(db_path)
    diffs: list[PresetDiff] = []
    for name in sorted(set(db_presets) | set(file_presets)):
        in_db, in_file = db_presets.get(name), file_presets.get(name)
        if in_file is not None and in_db is not None:
            file_vals, db_vals = _comparable(in_file), _comparable(in_db)
            changed = [k for k in file_vals if file_vals[k] != db_vals[k]]
            status: Status = "changed" if changed else "same"
            fdiffs = [FieldDiff(k, file_vals[k], db_vals[k]) for k in changed]
        elif in_file is not None:
            status, fdiffs = "added", []
        else:
            status, fdiffs = "db_only", []
        actions = _valid_actions(status)
        # Mặc định: file thắng khi file có preset, DB thắng khi chỉ DB có,
        # giống hệt thì không đụng. Đây chỉ là GỢI Ý — UI cho chọn lại từng preset.
        default = SKIP if status == "same" else (EXPORT if status == "db_only" else IMPORT)
        diffs.append(PresetDiff(name, status, default, actions, fdiffs))
    return SyncPlan(
        path=str(path),
        layout=layout,
        exists=Path(path).exists(),
        file_order=list(file_order if file_order is not None else file_presets.keys()),
        diffs=diffs,
        warnings=list(warnings or []),
    )


# ── ghi ─────────────────────────────────────────────────────────────────

@dataclass
class SyncReport:
    path: str
    layout: str
    imported: list[str] = field(default_factory=list)
    exported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    file_written: bool = False
    backup: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "layout": self.layout,
            "imported": self.imported,
            "exported": self.exported,
            "skipped": self.skipped,
            "file_written": self.file_written,
            "backup": self.backup,
            "warnings": self.warnings,
        }


def _resolve_action(diff: PresetDiff, action: str) -> Action:
    action = (action or "").strip().lower()
    if action not in diff.actions:
        raise SyncError(
            f"'{diff.name}': không hợp lệ. Chỉ nhận "
            + ", ".join(ACTION_LABELS[a] for a in diff.actions)
            + "."
        )
    return action  # type: ignore[return-value]


def apply_sync(
    db_path: str | Path,
    path: str | Path,
    file_presets: dict[str, SourcePreset],
    choices: dict[str, str],
    layout: str = FLAT,
    warnings: list[str] | None = None,
) -> SyncReport:
    """Thi hành lựa chọn: ghi DB rồi ghi ngược file. Trả `SyncReport`.

    - `import` → DB nhận bản của file (không ghi file: giữ nguyên từng ký tự).
    - `export` → file nhận bản của DB (DB không đổi).
    - `skip`   → không đụng DB, giữ nguyên entry trong file.
    - Preset có trong diff nhưng không kê trong `choices` → coi như `skip`.

    `choices` BẮT BUỘC, và tên preset không tồn tại trong diff thì báo lỗi — gõ
    nhầm tên rồi bị bỏ qua âm thầm còn tệ hơn là không đồng bộ.
    """
    path = Path(path)
    choices = choices or {}
    plan = plan_sync(db_path, path, file_presets, layout=layout, warnings=warnings)
    known = {d.name for d in plan.diffs}
    unknown = sorted(set(choices) - known)
    if unknown:
        raise SyncError(
            "Không có preset nào tên "
            + ", ".join(repr(n) for n in unknown[:5])
            + " trong file lẫn DB — kiểm tra lại tên đã chọn."
        )
    db_presets = load_presets(db_path)
    report = SyncReport(path=str(path), layout=layout, warnings=list(warnings or []))

    resolved: dict[str, SourcePreset] = {}
    for diff in plan.diffs:
        action = _resolve_action(diff, choices.get(diff.name, SKIP))
        if action == IMPORT:
            preset = file_presets[diff.name]
            save_preset(db_path, preset)
            resolved[diff.name] = preset
            report.imported.append(diff.name)
        elif action == EXPORT:
            preset = db_presets[diff.name]
            resolved[diff.name] = preset
            report.exported.append(diff.name)
        else:
            report.skipped.append(diff.name)
            # Giữ nguyên entry của file để không mất preset bị skip.
            if diff.name in file_presets:
                resolved[diff.name] = file_presets[diff.name]

    if report.imported or report.exported:
        backup = _write_sources_file(path, layout, resolved, plan.file_order)
        report.file_written = True
        report.backup = backup
    return report


def _dump_presets(layout: str, presets: dict[str, SourcePreset], order: list[str]) -> str:
    def block(names: list[str]) -> dict[str, Any]:
        return {
            name: {k: v for k, v in asdict(presets[name]).items() if k != "name"}
            for name in names
            if name in presets
        }

    # Thứ tự cũ trước (đổi file tối thiểu), preset mới thêm vào cuối theo alphabet.
    names = [n for n in order if n in presets]
    names += sorted(n for n in presets if n not in names)
    payload: dict[str, Any] = {"sources": block(names)} if layout == WRAPPED else block(names)
    return yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        # Regex/prompt dài bị wrap nhiều dòng thì đọc rối; giữ mỗi giá trị trên
        # một dòng (dài hơn 1000 ký tự thì vẫn wrap — chấp nhận được).
        width=4096,
    )


def _write_sources_file(
    path: Path,
    layout: str,
    presets: dict[str, SourcePreset],
    order: list[str],
) -> str:
    """Ghi file atomic; backup bản cũ trước. Trả đường dẫn backup ('' = file mới)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _dump_presets(layout, presets, order)
    backup = ""
    if path.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup_path = path.with_name(f"{path.stem}.bak-{stamp}{path.suffix}")
        counter = 2
        while backup_path.exists():
            backup_path = path.with_name(f"{path.stem}.bak-{stamp}-{counter}{path.suffix}")
            counter += 1
        shutil.copy2(path, backup_path)
        backup = str(backup_path)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    # os.replace là atomic trên cùng volume: không có trạng thái "file nửa viết"
    # nếu tiến trình chết giữa chừng.
    os.replace(tmp, path)
    return backup
