from novel2epub.ai_providers import AiProviderPreset, delete_preset, load_presets, save_preset
from novel2epub.db import get_connection, init_schema


def _init_db(path):
    conn = get_connection(path)
    init_schema(conn)
    return conn


def test_save_and_load_preset_roundtrip(tmp_path):
    path = tmp_path / "novel2epub.db"
    _init_db(path)

    save_preset(path, AiProviderPreset(name="OpenRouter", base_url="https://openrouter.ai/api/v1"))
    save_preset(path, AiProviderPreset(name="DeepSeek", base_url="https://api.deepseek.com/v1"))

    presets = load_presets(path)
    assert set(presets) == {"OpenRouter", "DeepSeek"}
    assert presets["OpenRouter"].base_url == "https://openrouter.ai/api/v1"


def test_save_preset_upserts_by_name(tmp_path):
    path = tmp_path / "novel2epub.db"
    _init_db(path)

    save_preset(path, AiProviderPreset(name="Custom", base_url="https://old.example/v1"))
    save_preset(path, AiProviderPreset(name="Custom", base_url="https://new.example/v1"))

    presets = load_presets(path)
    assert len(presets) == 1
    assert presets["Custom"].base_url == "https://new.example/v1"


def test_delete_preset_removes_only_named_entry(tmp_path):
    path = tmp_path / "novel2epub.db"
    _init_db(path)

    save_preset(path, AiProviderPreset(name="A", base_url="https://a.example/v1"))
    save_preset(path, AiProviderPreset(name="B", base_url="https://b.example/v1"))

    delete_preset(path, "A")

    presets = load_presets(path)
    assert set(presets) == {"B"}


def test_delete_preset_missing_name_is_noop(tmp_path):
    path = tmp_path / "novel2epub.db"
    _init_db(path)

    delete_preset(path, "không-tồn-tại")  # không raise

    assert load_presets(path) == {}


def test_load_presets_missing_db_returns_empty(tmp_path):
    assert load_presets(tmp_path / "khong-ton-tai.db") == {}
