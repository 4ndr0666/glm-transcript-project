"""
One-click video downloader (YouTube / Bilibili / and any site yt-dlp supports)
-----------------------------------------------------------------------------
Requirements:
    pip install -U "yt-dlp[default]"
    pip install -U openai-whisper   (optional, only needed for transcription)
    ffmpeg must be installed and on PATH (needed to merge video+audio streams,
    and used internally by whisper to decode audio)

Run:
    python video_downloader.py
"""

import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    import whisper
except ImportError:
    whisper = None

AUDIO_VIDEO_EXTS = (
    ".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus",
    ".mp4", ".mkv", ".webm", ".mov", ".avi",
)

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large"]
WHISPER_LANGUAGES = {
    "自动识别": None,
    "中文": "Chinese",
    "英语": "English",
    "西班牙语": "Spanish",
}
TRANSCRIPT_FORMATS = ["干净版 (Clean)", "带时间戳版 (Timestamped)", "两者都要 (Both)"]

# ----------------------------------------------------------------------------
# Quality presets: label -> (format selector, extra options)
# ----------------------------------------------------------------------------
QUALITY_PRESETS = {
    "最佳画质 (Best)": {
        "format": "bv*+ba/b",
    },
    "兼容模式 (H.264 + AAC, 任何播放器都能放)": {
        "format": "bv*+ba/b",
        "format_sort": ["vcodec:h264", "res", "acodec:m4a"],
    },
    "最高 1080p": {
        "format": "bv*[height<=1080]+ba/b[height<=1080]",
    },
    "最高 720p": {
        "format": "bv*[height<=720]+ba/b[height<=720]",
    },
    "仅音频 (MP3)": {
        "format": "ba/b",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    },
}

COOKIE_CHOICES = ["不使用", "firefox", "chrome", "edge", "brave", "chromium", "opera", "safari"]


class QueueLogger:
    """Routes yt-dlp's internal log messages into the GUI queue."""

    def __init__(self, q):
        self.q = q

    def debug(self, msg):
        if not msg.startswith("[debug]"):
            self.q.put(("log", msg))

    def info(self, msg):
        self.q.put(("log", msg))

    def warning(self, msg):
        self.q.put(("log", "⚠ " + msg))

    def error(self, msg):
        self.q.put(("log", "✖ " + msg))


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.busy = False

        root.title("Video Downloader ^^")
        root.geometry("720x560")
        root.minsize(620, 480)

        self.url_var = tk.StringVar()
        self.dir_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Downloads"))
        self.quality_var = tk.StringVar(value=list(QUALITY_PRESETS)[0])
        self.cookie_var = tk.StringVar(value=COOKIE_CHOICES[0])
        self.playlist_var = tk.BooleanVar(value=False)
        self.sub_var = tk.BooleanVar(value=False)

        self.auto_transcribe_var = tk.BooleanVar(value=False)
        self.whisper_model_var = tk.StringVar(value="small")
        self.whisper_lang_var = tk.StringVar(value="自动识别")
        self.transcript_format_var = tk.StringVar(value=TRANSCRIPT_FORMATS[2])
        self.transcript_dir_var = tk.StringVar(
            value=os.path.dirname(os.path.abspath(__file__))
        )
        self.weak_network_var = tk.BooleanVar(value=False)
        self._last_downloaded_file = None

        self._build_ui()
        self._prefill_clipboard()
        self._check_environment()
        self.root.after(100, self._poll_queue)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        pad = {"padx": 10, "pady": 5}
        frm = ttk.Frame(self.root)
        frm.pack(fill="both", expand=True, padx=8, pady=8)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="视频链接").grid(row=0, column=0, sticky="w", **pad)
        url_entry = ttk.Entry(frm, textvariable=self.url_var)
        url_entry.grid(row=0, column=1, sticky="ew", **pad)
        url_entry.bind("<Return>", lambda e: self.start())
        ttk.Button(frm, text="粘贴", width=6, command=self.paste).grid(row=0, column=2, **pad)

        ttk.Label(frm, text="保存到").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.dir_var).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="选择", width=6, command=self.choose_dir).grid(row=1, column=2, **pad)

        ttk.Label(frm, text="画质").grid(row=2, column=0, sticky="w", **pad)
        ttk.Combobox(
            frm, textvariable=self.quality_var, values=list(QUALITY_PRESETS), state="readonly"
        ).grid(row=2, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Label(frm, text="登录态(Cookie)").grid(row=3, column=0, sticky="w", **pad)
        ttk.Combobox(
            frm, textvariable=self.cookie_var, values=COOKIE_CHOICES, state="readonly"
        ).grid(row=3, column=1, columnspan=2, sticky="ew", **pad)

        opts = ttk.Frame(frm)
        opts.grid(row=4, column=0, columnspan=3, sticky="w", **pad)
        ttk.Checkbutton(opts, text="下载整个列表 / 全部分P", variable=self.playlist_var).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(opts, text="同时下载字幕", variable=self.sub_var).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(
            opts, text="弱网模式 (降低并发，更稳但更慢)", variable=self.weak_network_var
        ).pack(side="left")

        # ---- Transcription options -----------------------------------
        trans_frame = ttk.LabelFrame(frm, text="转录 (Whisper)")
        trans_frame.grid(row=5, column=0, columnspan=3, sticky="ew", **pad)
        trans_frame.columnconfigure(3, weight=1)

        ttk.Checkbutton(
            trans_frame, text="下载完成后自动转录", variable=self.auto_transcribe_var
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=4)

        ttk.Label(trans_frame, text="模型").grid(row=0, column=2, sticky="e", padx=(12, 4))
        ttk.Combobox(
            trans_frame, textvariable=self.whisper_model_var, values=WHISPER_MODELS,
            state="readonly", width=8,
        ).grid(row=0, column=3, sticky="w")

        ttk.Label(trans_frame, text="语言").grid(row=1, column=2, sticky="e", padx=(12, 4))
        ttk.Combobox(
            trans_frame, textvariable=self.whisper_lang_var, values=list(WHISPER_LANGUAGES),
            state="readonly", width=8,
        ).grid(row=1, column=3, sticky="w")

        ttk.Label(trans_frame, text="输出").grid(row=2, column=2, sticky="e", padx=(12, 4))
        ttk.Combobox(
            trans_frame, textvariable=self.transcript_format_var, values=TRANSCRIPT_FORMATS,
            state="readonly", width=20,
        ).grid(row=2, column=3, sticky="w")

        ttk.Button(
            trans_frame, text="转录本地文件…", command=self.transcribe_local_file
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=4)

        ttk.Label(trans_frame, text="字幕保存至").grid(row=2, column=0, sticky="w", padx=6)
        ttk.Entry(trans_frame, textvariable=self.transcript_dir_var).grid(
            row=2, column=1, sticky="ew", padx=4
        )
        ttk.Button(trans_frame, text="选择", width=6, command=self.choose_transcript_dir).grid(
            row=3, column=0, sticky="w", padx=6, pady=(0, 4)
        )

        btns = ttk.Frame(frm)
        btns.grid(row=6, column=0, columnspan=3, sticky="ew", **pad)
        self.dl_btn = ttk.Button(btns, text="⬇  开始下载", command=self.start)
        self.dl_btn.pack(side="left")
        ttk.Button(btns, text="打开文件夹", command=self.open_dir).pack(side="left", padx=8)
        ttk.Button(btns, text="更新 yt-dlp", command=self.update_ytdlp).pack(side="left")

        self.progress = ttk.Progressbar(frm, maximum=100)
        self.progress.grid(row=7, column=0, columnspan=3, sticky="ew", **pad)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(frm, textvariable=self.status_var).grid(row=8, column=0, columnspan=3, sticky="w", **pad)

        log_frame = ttk.Frame(frm)
        log_frame.grid(row=9, column=0, columnspan=3, sticky="nsew", **pad)
        frm.rowconfigure(9, weight=1)
        self.log = tk.Text(log_frame, height=10, wrap="word", state="disabled")
        sb = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ------------------------------------------------------------- helpers
    def _prefill_clipboard(self):
        try:
            clip = self.root.clipboard_get().strip()
            if clip.startswith(("http://", "https://")):
                self.url_var.set(clip)
        except tk.TclError:
            pass

    def _check_environment(self):
        if yt_dlp is None:
            self.write_log('未找到 yt-dlp，请先运行：pip install -U "yt-dlp[default]"')
        if shutil.which("ffmpeg") is None:
            self.write_log("⚠ 未检测到 ffmpeg：高画质需要合并音视频流，请安装 ffmpeg 并加入 PATH。")
        if whisper is None:
            self.write_log("ℹ 未找到 whisper，转录功能不可用。需要时运行：pip install -U openai-whisper")

    def write_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def paste(self):
        try:
            self.url_var.set(self.root.clipboard_get().strip())
        except tk.TclError:
            pass

    def choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.dir_var.get())
        if d:
            self.dir_var.set(d)

    def choose_transcript_dir(self):
        d = filedialog.askdirectory(initialdir=self.transcript_dir_var.get())
        if d:
            self.transcript_dir_var.set(d)

    def open_dir(self):
        path = self.dir_var.get()
        os.makedirs(path, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def set_busy(self, busy):
        self.busy = busy
        self.dl_btn.configure(state="disabled" if busy else "normal")

    # ------------------------------------------------------------ download
    def build_opts(self):
        preset = dict(QUALITY_PRESETS[self.quality_var.get()])
        out_dir = self.dir_var.get()
        os.makedirs(out_dir, exist_ok=True)

        opts = {
            "outtmpl": os.path.join(out_dir, "%(title)s [%(id)s].%(ext)s"),
            "noplaylist": not self.playlist_var.get(),
            "progress_hooks": [self.progress_hook],
            "logger": QueueLogger(self.q),
            "no_color": True,
            "windowsfilenames": True,
            "trim_file_name": 120,
            "retries": "infinite",
            "fragment_retries": "infinite",
            "merge_output_format": "mp4",
            "concurrent_fragment_downloads": 1 if self.weak_network_var.get() else 4,
        }
        opts.update(preset)

        cookie = self.cookie_var.get()
        if cookie != COOKIE_CHOICES[0]:
            opts["cookiesfrombrowser"] = (cookie,)

        if self.sub_var.get():
            opts["writesubtitles"] = True
            opts["writeautomaticsub"] = False
            opts["subtitleslangs"] = ["zh.*", "en.*", "ai-zh"]

        return opts

    def start(self):
        if self.busy:
            return
        if yt_dlp is None:
            messagebox.showerror("缺少依赖", '请先运行：pip install -U "yt-dlp[default]"')
            return
        url = self.url_var.get().strip()
        if not url.startswith(("http://", "https://")):
            messagebox.showwarning("链接无效", "请输入以 http(s):// 开头的视频链接。")
            return

        self.set_busy(True)
        self.progress["value"] = 0
        self.status_var.set("准备中…")
        threading.Thread(target=self._worker, args=(url,), daemon=True).start()

    def _worker(self, url):
        try:
            with yt_dlp.YoutubeDL(self.build_opts()) as ydl:
                info = ydl.extract_info(url)
                # extract_info already triggers the download; get the final
                # on-disk path so we know what to feed into Whisper later.
                try:
                    filepath = ydl.prepare_filename(info)
                    if self.quality_var.get() == "仅音频 (MP3)":
                        # the postprocessor renames .webm/.m4a -> .mp3
                        filepath = os.path.splitext(filepath)[0] + ".mp3"
                    self._last_downloaded_file = filepath
                except Exception:  # noqa: BLE001
                    self._last_downloaded_file = None
            self.q.put(("done", True))
        except Exception as e:  # noqa: BLE001
            self.q.put(("log", f"✖ 出错：{e}"))
            self.q.put(("done", False))

    def progress_hook(self, d):
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            pct = (done / total * 100) if total else 0
            speed = d.get("speed")
            eta = d.get("eta")
            parts = [f"{pct:5.1f}%"]
            if speed:
                parts.append(f"{speed / 1024 / 1024:.2f} MiB/s")
            if eta is not None:
                parts.append(f"剩余 {int(eta)}s")
            self.q.put(("progress", pct, "下载中  " + " · ".join(parts)))
        elif status == "finished":
            self.q.put(("progress", 100, "下载完成，正在合并/处理…"))

    # ----------------------------------------------------------- transcribe
    def transcribe_local_file(self):
        if self.busy:
            return
        if whisper is None:
            messagebox.showerror("缺少依赖", "请先运行：pip install -U openai-whisper")
            return
        path = filedialog.askopenfilename(
            title="选择要转录的音频/视频文件",
            filetypes=[("音视频文件", " ".join("*" + e for e in AUDIO_VIDEO_EXTS)), ("所有文件", "*.*")],
        )
        if path:
            self._start_transcription(path)

    def _start_transcription(self, path):
        self.set_busy(True)
        self.status_var.set("转录中…（第一次用某个模型会先下载模型文件，稍等一下）")
        self.progress["value"] = 0
        threading.Thread(target=self._transcribe_worker, args=(path,), daemon=True).start()

    def _transcribe_worker(self, path):
        try:
            model_name = self.whisper_model_var.get()
            language = WHISPER_LANGUAGES.get(self.whisper_lang_var.get())

            self.q.put(("log", f"加载 Whisper 模型：{model_name} …"))
            model = whisper.load_model(model_name)

            self.q.put(("log", f"开始转录：{os.path.basename(path)}"))
            result = model.transcribe(path, language=language, verbose=False)

            segments = result.get("segments", [])
            stem = os.path.splitext(os.path.basename(path))[0]
            out_dir = self.transcript_dir_var.get().strip() or os.path.dirname(path)
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.join(out_dir, stem)
            fmt_choice = self.transcript_format_var.get()
            want_clean = fmt_choice in (TRANSCRIPT_FORMATS[0], TRANSCRIPT_FORMATS[2])
            want_ts = fmt_choice in (TRANSCRIPT_FORMATS[1], TRANSCRIPT_FORMATS[2])

            if want_clean:
                clean_lines = [seg["text"].strip() for seg in segments if seg["text"].strip()]
                clean_path = base + "_transcript_clean.txt"
                with open(clean_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(clean_lines))
                self.q.put(("log", f"✔ 转录完成：{clean_path}"))

            if want_ts:
                ts_lines = []
                for seg in segments:
                    text = seg["text"].strip()
                    if not text:
                        continue
                    start = int(seg["start"])
                    mm, ss = divmod(start, 60)
                    hh, mm = divmod(mm, 60)
                    ts = f"{hh:02d}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}"
                    ts_lines.append(f"[{ts}] {text}")
                ts_path = base + "_transcript_timestamped.txt"
                with open(ts_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(ts_lines))
                self.q.put(("log", f"✔ 转录完成：{ts_path}"))

            self.q.put(("done", True))
        except Exception as e:  # noqa: BLE001
            self.q.put(("log", f"✖ 转录出错：{e}"))
            self.q.put(("done", False))

    # --------------------------------------------------------- yt-dlp update
    def update_ytdlp(self):
        if self.busy:
            return
        self.set_busy(True)
        self.status_var.set("正在更新 yt-dlp…")

        def run():
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"],
                    capture_output=True, text=True,
                )
                tail = (proc.stdout or proc.stderr).strip().splitlines()[-1:]
                self.q.put(("log", "更新结果：" + (tail[0] if tail else "完成") + "（需重启程序生效）"))
            except Exception as e:  # noqa: BLE001
                self.q.put(("log", f"✖ 更新失败：{e}"))
            self.q.put(("done", None))

        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------- queue loop
    def _poll_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self.write_log(item[1])
                elif kind == "progress":
                    self.progress["value"] = item[1]
                    self.status_var.set(item[2])
                elif kind == "done":
                    self.set_busy(False)
                    if item[1] is True:
                        self.progress["value"] = 100
                        self.status_var.set("✔ 全部完成")
                        # If a download just finished (not a transcription
                        # job) and auto-transcribe is on, chain into it.
                        if (
                            self.auto_transcribe_var.get()
                            and self._last_downloaded_file
                            and os.path.exists(self._last_downloaded_file)
                        ):
                            pending_file = self._last_downloaded_file
                            self._last_downloaded_file = None  # avoid re-trigger loop
                            if whisper is None:
                                self.write_log("⚠ 想自动转录，但没装 whisper，跳过。运行：pip install -U openai-whisper")
                            else:
                                self._start_transcription(pending_file)
                    elif item[1] is False:
                        self.status_var.set("✖ 失败，详见下方日志")
                    else:
                        self.status_var.set("就绪")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
