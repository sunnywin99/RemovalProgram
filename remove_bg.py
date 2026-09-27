"""
衣物去背小工具
--------------
本機執行的簡易去背程式，可一次選取多張照片，自動去除背景並輸出透明底 PNG。

使用方式：
    python remove_bg.py

第一次執行會自動下載 AI 去背模型（約 170MB），需要網路連線，之後即可離線使用。
"""

import queue
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image
from rembg import remove, new_session

MODEL_NAME = "isnet-general-use"  # 通用去背模型，邊緣細節比 u2net 更乾淨
IMAGE_FILETYPES = [
    ("圖片檔", "*.jpg *.jpeg *.png *.bmp *.webp"),
    ("所有檔案", "*.*"),
]


class BgRemoverApp:
    def __init__(self, root):
        self.root = root
        root.title("衣物去背小工具")
        root.geometry("640x480")
        root.minsize(560, 420)

        self.files = []
        self.output_dir = None
        self.session = None
        self.msg_queue = queue.Queue()
        self.bg_choice = tk.StringVar(value="transparent")

        self._build_ui()
        self._poll_queue()

    def _build_ui(self):
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Button(top, text="選擇照片…（可複選）", command=self.choose_files).pack(side="left")
        ttk.Button(top, text="選擇輸出資料夾…", command=self.choose_output_dir).pack(side="left", padx=(8, 0))
        self.run_btn = ttk.Button(top, text="開始去背", command=self.start_processing)
        self.run_btn.pack(side="right")

        self.output_label = ttk.Label(
            self.root,
            text="輸出資料夾：未選擇（預設會在每張照片旁自動建立「去背結果」資料夾）",
            foreground="gray",
        )
        self.output_label.pack(fill="x", padx=10)

        bg_frame = ttk.Frame(self.root)
        bg_frame.pack(fill="x", padx=10, pady=(4, 0))
        ttk.Label(bg_frame, text="輸出背景：").pack(side="left")
        ttk.Radiobutton(bg_frame, text="透明", variable=self.bg_choice, value="transparent").pack(side="left", padx=(4, 0))
        ttk.Radiobutton(bg_frame, text="白色", variable=self.bg_choice, value="white").pack(side="left", padx=(8, 0))

        list_frame = ttk.LabelFrame(self.root, text="已選擇的照片")
        list_frame.pack(fill="both", expand=True, padx=10, pady=6)

        self.listbox = tk.Listbox(list_frame, selectmode="extended")
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=scrollbar.set)

        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.pack(fill="x", padx=10, pady=(0, 6))

        self.status_var = tk.StringVar(value="請選擇要去背的照片（可一次選多張）")
        ttk.Label(self.root, textvariable=self.status_var).pack(fill="x", padx=10, pady=(0, 10))

    def choose_files(self):
        paths = filedialog.askopenfilenames(
            title="選擇要去背的照片（可複選）",
            filetypes=IMAGE_FILETYPES,
        )
        if not paths:
            return
        self.files = list(paths)
        self.listbox.delete(0, "end")
        for p in self.files:
            self.listbox.insert("end", p)
        self.status_var.set(f"已選擇 {len(self.files)} 張照片")

    def choose_output_dir(self):
        d = filedialog.askdirectory(title="選擇輸出資料夾")
        if d:
            self.output_dir = d
            self.output_label.config(text=f"輸出資料夾：{d}")

    def start_processing(self):
        if not self.files:
            messagebox.showwarning("尚未選擇照片", "請先選擇要去背的照片。")
            return
        self.run_btn.config(state="disabled")
        self.progress.config(maximum=len(self.files), value=0)
        bg_mode = self.bg_choice.get()
        thread = threading.Thread(target=self._process_worker, args=(bg_mode,), daemon=True)
        thread.start()

    def _process_worker(self, bg_mode):
        try:
            if self.session is None:
                self.msg_queue.put(("status", "首次執行需下載 AI 模型，請稍候…"))
                self.session = new_session(MODEL_NAME)

            out_dir = self.output_dir
            done = 0
            errors = []
            for src in self.files:
                src_path = Path(src)
                target_dir = Path(out_dir) if out_dir else src_path.parent / "去背結果"
                target_dir.mkdir(parents=True, exist_ok=True)
                suffix = "_nobg" if bg_mode == "transparent" else "_white"
                dest_path = target_dir / (src_path.stem + suffix + ".png")

                try:
                    with Image.open(src_path) as img:
                        img = img.convert("RGBA")
                        result = remove(
                            img,
                            session=self.session,
                            alpha_matting=True,
                            alpha_matting_foreground_threshold=270,
                            alpha_matting_background_threshold=20,
                            alpha_matting_erode_size=11,
                            post_process_mask=True,
                        )
                        if bg_mode == "white":
                            canvas = Image.new("RGBA", result.size, (255, 255, 255, 255))
                            canvas.alpha_composite(result)
                            result = canvas.convert("RGB")
                        result.save(dest_path)
                except Exception as e:
                    errors.append(f"{src_path.name}：{e}")

                done += 1
                self.msg_queue.put(("progress", done))
                self.msg_queue.put(("status", f"處理中… ({done}/{len(self.files)}) {src_path.name}"))

            self.msg_queue.put(("done", (done, errors, out_dir or "各照片旁的「去背結果」資料夾")))
        except Exception as e:
            self.msg_queue.put(("fatal", str(e)))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "status":
                    self.status_var.set(payload)
                elif kind == "progress":
                    self.progress.config(value=payload)
                elif kind == "done":
                    done, errors, out_dir = payload
                    self.run_btn.config(state="normal")
                    if errors:
                        self.status_var.set(f"完成 {done} 張，其中 {len(errors)} 張失敗")
                        messagebox.showwarning("部分失敗", "以下照片處理失敗：\n" + "\n".join(errors))
                    else:
                        self.status_var.set(f"完成！共處理 {done} 張照片")
                        messagebox.showinfo("完成", f"已完成 {done} 張照片去背！\n輸出位置：{out_dir}")
                elif kind == "fatal":
                    self.run_btn.config(state="normal")
                    messagebox.showerror("發生錯誤", payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)


def main():
    root = tk.Tk()
    BgRemoverApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
