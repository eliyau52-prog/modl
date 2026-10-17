"""מתמלל מקומי: pywebview + faster-whisper (תמלול) + llama-cpp-python (Qwen 2.5 Instruct).

המודלים נטענים ישירות בתוך התוכנה, בלי שרת ובלי כתובות.
"""
import json
import sys
import threading
from pathlib import Path

import webview
from webview.dom import DOMEventHandler

FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent
RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
CONFIG_PATH = APP_DIR / "config.json"

DEFAULTS = {
    "whisper_model": "large-v3",   # שם מודל (יורד פעם אחת מהרשת) או נתיב לתיקיית מודל CTranslate2
    "qwen_gguf": "",               # נתיב לקובץ .gguf של Qwen 2.5 Instruct
    "gpu_layers": 0,               # 0 = CPU בלבד, -1 = כל השכבות על ה-GPU (אם יש build תומך)
    "language": "he",
    "mode": "clean",
    "custom_prompt": "",
}

WINDOW = None
_lock = threading.Lock()


def load_config():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass
    return cfg


def _dlg(kind):
    fd = getattr(webview, "FileDialog", None)
    if fd:
        return getattr(fd, kind)
    return getattr(webview, kind + "_DIALOG")


def _js(fn, *args):
    if WINDOW:
        WINDOW.evaluate_js(f"window.{fn}({','.join(json.dumps(a) for a in args)})")


def _chunk(text, size=5000):
    import re
    parts, cur = [], ""
    for s in re.split(r"(?<=[.!?])\s+", text):
        if len(cur) + len(s) > size and cur:
            parts.append(cur)
            cur = ""
        cur += s + " "
    if cur.strip():
        parts.append(cur)
    return parts


class Api:
    """כל מתודה ציבורית כאן נגישה מהדף דרך window.pywebview.api"""

    def __init__(self):
        self._whisper = None
        self._whisper_key = None
        self._llm = None
        self._llm_key = None

    # ---------- הגדרות ----------
    def get_config(self):
        return load_config()

    def set_config(self, cfg):
        merged = load_config()
        merged.update(cfg)
        CONFIG_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    def browse_folder(self):
        r = WINDOW.create_file_dialog(_dlg("FOLDER"))
        return r[0] if r else ""

    def browse_gguf(self):
        r = WINDOW.create_file_dialog(_dlg("OPEN"), file_types=("GGUF model (*.gguf)", "All files (*.*)"))
        return r[0] if r else ""

    def pick_audio(self):
        r = WINDOW.create_file_dialog(
            _dlg("OPEN"),
            allow_multiple=True,
            file_types=("Audio/Video (*.mp3;*.wav;*.m4a;*.ogg;*.flac;*.aac;*.wma;*.mp4;*.mkv;*.webm;*.mov)", "All files (*.*)"),
        )
        return list(r) if r else []

    def save_text(self, suggested_name, text):
        r = WINDOW.create_file_dialog(_dlg("SAVE"), save_filename=suggested_name)
        if not r:
            return False
        path = r if isinstance(r, str) else r[0]
        Path(path).write_text(text, encoding="utf-8")
        return True

    # ---------- תמלול ----------
    def _get_whisper(self):
        cfg = load_config()
        key = cfg["whisper_model"]
        with _lock:
            if self._whisper is None or self._whisper_key != key:
                from faster_whisper import WhisperModel
                _js("onStatusGlobal", "טוען מודל תמלול…")
                self._whisper = WhisperModel(key, device="auto", compute_type="auto")
                self._whisper_key = key
                _js("onStatusGlobal", "")
        return self._whisper

    def transcribe(self, path, language):
        try:
            model = self._get_whisper()
            segments, info = model.transcribe(path, language=language or None, vad_filter=True, beam_size=5)
            total = info.duration or 1
            parts = []
            for seg in segments:
                parts.append(seg.text.strip())
                _js("onProgress", path, min(99, int(seg.end / total * 100)))
            return {"ok": True, "text": " ".join(parts)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    # ---------- Qwen ----------
    def _get_llm(self):
        cfg = load_config()
        key = (cfg["qwen_gguf"], cfg["gpu_layers"])
        if not cfg["qwen_gguf"] or not Path(cfg["qwen_gguf"]).exists():
            raise RuntimeError("לא נבחר קובץ GGUF של Qwen בהגדרות")
        with _lock:
            if self._llm is None or self._llm_key != key:
                from llama_cpp import Llama
                _js("onStatusGlobal", "טוען את Qwen…")
                self._llm = Llama(
                    model_path=cfg["qwen_gguf"],
                    n_ctx=8192,
                    n_gpu_layers=int(cfg["gpu_layers"]),
                    verbose=False,
                )
                self._llm_key = key
                _js("onStatusGlobal", "")
        return self._llm

    @staticmethod
    def _system_prompt(mode, custom):
        same = " ענה באותה שפה של הטקסט."
        if mode == "clean":
            return ("אתה עורך לשון. קיבלת תמלול גולמי של הקלטה. הוסף פיסוק, תקן שגיאות תמלול ברורות "
                    "וחלק לפסקאות. אל תוסיף, אל תסכם ואל תשנה את התוכן. החזר רק את הטקסט המתוקן." + same)
        if mode == "summary":
            return ("קיבלת תמלול של הקלטה. כתוב סיכום קצר ואחריו נקודות עיקריות ומשימות (אם יש). "
                    "אל תמציא מידע שלא נאמר." + same)
        return (custom or "עבד את הטקסט.") + same

    def refine(self, text, mode, custom, path):
        try:
            llm = self._get_llm()
            sysmsg = self._system_prompt(mode, custom)
            parts = _chunk(text) if mode == "clean" else [text[:24000]]
            out = []
            for i, p in enumerate(parts, 1):
                _js("onStage", path, f"מעבד עם Qwen ({i}/{len(parts)})…")
                r = llm.create_chat_completion(
                    messages=[{"role": "system", "content": sysmsg}, {"role": "user", "content": p}],
                    temperature=0.2,
                )
                out.append(r["choices"][0]["message"]["content"].strip())
            return {"ok": True, "text": "\n\n".join(out)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}


def _on_drop(e):
    files = e.get("dataTransfer", {}).get("files", [])
    paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
    if paths:
        _js("addPaths", paths)


def _bind(window):
    window.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, False)
    window.dom.document.events.drop += DOMEventHandler(_on_drop, True, True)


def main():
    global WINDOW
    index = RES_DIR / "web" / "index.html"
    WINDOW = webview.create_window("מתמלל מקומי", str(index), js_api=Api(), width=980, height=820)
    webview.start(_bind, WINDOW)


if __name__ == "__main__":
    main()
