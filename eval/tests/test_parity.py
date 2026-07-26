"""Guards the claim that the benchmark measures what the app actually ships.

If someone tunes the temperature in the Rust app, or edits the prompt only on
one side, these tests fail — which is the whole point. A benchmark that has
quietly drifted from the product is worse than no benchmark.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clarion_eval import providers  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RUST_STRUCTURE_MOD = REPO_ROOT / "src-tauri" / "src" / "structure" / "mod.rs"


def _rust_source() -> str:
    return RUST_STRUCTURE_MOD.read_text(encoding="utf-8")


def test_prompt_file_exists_and_is_nonempty():
    assert providers.PROMPT_PATH.exists(), providers.PROMPT_PATH
    assert providers.system_prompt().strip()


def test_rust_embeds_the_same_prompt_file():
    """The Rust side must include_str! the exact file Python reads."""
    source = _rust_source()
    match = re.search(r'include_str!\("([^"]+)"\)', source)
    assert match, "structure/mod.rs no longer embeds a prompt file"

    embedded = (RUST_STRUCTURE_MOD.parent / match.group(1)).resolve()
    assert embedded == providers.PROMPT_PATH.resolve(), (
        f"Rust embeds {embedded}, Python reads {providers.PROMPT_PATH.resolve()}"
    )


def test_temperature_matches_rust():
    match = re.search(r"TEMPERATURE:\s*f32\s*=\s*([0-9.]+)", _rust_source())
    assert match, "TEMPERATURE constant not found in structure/mod.rs"
    assert float(match.group(1)) == providers.TEMPERATURE


def test_max_tokens_matches_rust():
    match = re.search(r"MAX_TOKENS:\s*u32\s*=\s*(\d+)", _rust_source())
    assert match, "MAX_TOKENS constant not found in structure/mod.rs"
    assert int(match.group(1)) == providers.MAX_TOKENS


def test_user_message_wrapper_matches_rust():
    """Rust builds the user turn with a format! string; the shapes must agree."""
    match = re.search(
        r'format!\(\s*"(Raw voice transcription:.*?)"\s*\)', _rust_source(), re.DOTALL
    )
    assert match, "build_user_message format string not found in structure/mod.rs"

    rust_template = match.group(1).encode().decode("unicode_escape")
    rendered = rust_template.replace("{raw_text}", "SAMPLE")
    assert rendered == providers.user_message("SAMPLE")
