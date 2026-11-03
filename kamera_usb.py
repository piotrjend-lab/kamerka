"""Kamera USB - podgląd, zdjęcia i nagrywanie wideo (OpenCV + Tkinter)."""
import os
import platform
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import cv2
from PIL import Image, ImageTk

BACKENDS = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY] if sys.platform == "win32" else [cv2.CAP_ANY]
BACKEND = BACKENDS[0]
RESOLUTIONS = ["640x480", "800x600", "1280x720", "1920x1080"]
OUT_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "KameraUSB")


def log(msg):
    """Zapisuje diagnostykę do Obrazy\\KameraUSB\\kamera_log.txt."""
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(os.path.join(OUT_DIR, "kamera_log.txt"), "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except Exception:
        pass


def open_camera(idx, w, h):
    """Próbuje kolejnych backendów i trybów; zwraca (cap, opis) albo (None, None)."""
    log(f"START idx={idx} {w}x{h} opencv={cv2.__version__} win={platform.platform()}")
    for be in BACKENDS:
        for mjpg in (True, False):
            try:
                cap = cv2.VideoCapture(idx, be)
            except Exception as e:
                log(f"backend={be} mjpg={mjpg} WYJATEK przy otwieraniu: {e!r}")
                continue
            opened = cap.isOpened()
            log(f"backend={be} mjpg={mjpg} isOpened={opened}")
            if not opened:
                cap.release()
                continue
            if mjpg:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            cap.set(cv2.CAP_PROP_FPS, 30)
            ok = False
            for _ in range(10):
                ok, _f = cap.read()
                if ok:
                    break
            log(f"backend={be} mjpg={mjpg} read_ok={ok}")
            if ok:
                return cap, f"backend={be} mjpg={mjpg}"
            cap.release()
    return None, None


def find_cameras(max_index=6):
    found = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, BACKEND)
        if cap.isOpened():
            found.append(i)
        cap.release()
    return found


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Kamera USB")
        self.geometry("900x680")
        self.minsize(640, 520)
        self.cap = None
        self.writer = None
        self.frame = None
        self.raw = None
        self.running = False
        self.photo = None
        self.last_t = time.time()
        self.fps = 0.0
        os.makedirs(OUT_DIR, exist_ok=True)

        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text="Kamera:").pack(side="left")
        self.cam_var = tk.StringVar()
        self.cam_box = ttk.Combobox(top, textvariable=self.cam_var, width=12, state="readonly")
        self.cam_box.pack(side="left", padx=4)
        ttk.Label(top, text="Rozdzielczość:").pack(side="left", padx=(10, 0))
        self.res_var = tk.StringVar(value="640x480")
        ttk.Combobox(top, textvariable=self.res_var, values=RESOLUTIONS, width=10,
                     state="readonly").pack(side="left", padx=4)
        ttk.Button(top, text="Odśwież", command=self.refresh).pack(side="left", padx=4)
        self.start_btn = ttk.Button(top, text="Start", command=self.toggle_camera)
        self.start_btn.pack(side="left", padx=4)
        self.mirror = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Lustro", variable=self.mirror).pack(side="left", padx=8)

        self.view = tk.Label(self, bg="black")
        self.view.pack(fill="both", expand=True, padx=6, pady=4)

        bottom = ttk.Frame(self, padding=6)
        bottom.pack(fill="x")
        self.snap_btn = ttk.Button(bottom, text="Zrób zdjęcie", command=self.snapshot, state="disabled")
        self.snap_btn.pack(side="left")
        self.rec_btn = ttk.Button(bottom, text="Nagrywaj", command=self.toggle_record, state="disabled")
        self.rec_btn.pack(side="left", padx=6)
        ttk.Button(bottom, text="Otwórz folder", command=self.open_folder).pack(side="left")
        self.status = ttk.Label(bottom, text="Gotowe")
        self.status.pack(side="right")

        self.report_callback_exception = lambda *a: log("BLAD: " + "".join(
            __import__("traceback").format_exception(*a)))
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.refresh()
        self.after(30, self.loop)

    def refresh(self):
        if self.cap:
            self.status.config(text="Zatrzymaj kamerę przed odświeżeniem listy")
            return
        cams = find_cameras()
        self.cam_box["values"] = [f"Kamera {i}" for i in cams]
        if cams:
            self.cam_box.current(0)
            self.status.config(text=f"Znaleziono kamer: {len(cams)}")
        else:
            self.cam_var.set("")
            self.status.config(text="Nie znaleziono kamery")

    def toggle_camera(self):
        if self.cap:
            self.stop_camera()
            return
        if not self.cam_var.get():
            messagebox.showwarning("Kamera USB", "Nie wybrano kamery. Podłącz ją i kliknij Odśwież.")
            return
        idx = int(self.cam_var.get().split()[-1])
        w, h = map(int, self.res_var.get().split("x"))
        self.status.config(text="Otwieranie kamery...")
        self.update_idletasks()
        cap, info = open_camera(idx, w, h)
        if cap is None:
            messagebox.showerror(
                "Kamera USB",
                "Nie udało się uruchomić kamery.\n\n"
                "• Zamknij inne programy używające kamery (Teams, Zoom, przeglądarka, "
                "poprzednie okno tej aplikacji).\n"
                "• Ustawienia Windows → Prywatność → Aparat: zezwól aplikacjom klasycznym.\n"
                "• Spróbuj niższej rozdzielczości (640x480).\n\n"
                f"Diagnostyka: {os.path.join(OUT_DIR, 'kamera_log.txt')}")
            self.status.config(text="Błąd kamery")
            return
        self.status.config(text=f"Kamera OK ({info})")
        self.cap = cap
        self.raw = None
        self.running = True
        self.grab_thread = threading.Thread(target=self.grab_loop, args=(cap,), daemon=True)
        self.grab_thread.start()
        self.start_btn.config(text="Stop")
        self.snap_btn.config(state="normal")
        self.rec_btn.config(state="normal")

    def grab_loop(self, cap):
        try:
            while self.running and cap.isOpened():
                ok, f = cap.read()
                if ok:
                    self.raw = f
        finally:
            cap.release()  # zwalnia ten sam wątek, który czyta - inaczej kamera zostaje zablokowana
            log("kamera zwolniona")

    def stop_camera(self):
        self.stop_record()
        self.running = False
        t = getattr(self, "grab_thread", None)
        if t and t.is_alive():
            t.join(timeout=5)
        self.cap = None
        self.frame = None
        self.view.config(image="")
        self.start_btn.config(text="Start")
        self.snap_btn.config(state="disabled")
        self.rec_btn.config(state="disabled")
        self.status.config(text="Zatrzymano")

    def stamp(self, ext):
        return os.path.join(OUT_DIR, datetime.now().strftime("%Y%m%d_%H%M%S") + ext)

    def snapshot(self):
        if self.frame is None:
            return
        path = self.stamp(".jpg")
        cv2.imwrite(path, self.frame)
        self.status.config(text=f"Zapisano: {os.path.basename(path)}")

    def toggle_record(self):
        if self.writer:
            self.stop_record()
            return
        if self.frame is None:
            return
        h, w = self.frame.shape[:2]
        path = self.stamp(".avi")
        self.writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 25, (w, h))
        self.rec_btn.config(text="Zatrzymaj nagrywanie")
        self.status.config(text=f"Nagrywanie: {os.path.basename(path)}")

    def stop_record(self):
        if self.writer:
            self.writer.release()
            self.writer = None
            self.rec_btn.config(text="Nagrywaj")
            self.status.config(text="Nagranie zapisane")

    def open_folder(self):
        if sys.platform == "win32":
            os.startfile(OUT_DIR)
        else:
            os.system(f'xdg-open "{OUT_DIR}" >/dev/null 2>&1 &')

    def loop(self):
        if self.cap:
            frame, self.raw = self.raw, None
            if frame is not None:
                if self.mirror.get():
                    frame = cv2.flip(frame, 1)
                self.frame = frame
                if self.writer:
                    self.writer.write(frame)
                now = time.time()
                self.fps = 0.9 * self.fps + 0.1 / max(now - self.last_t, 1e-3)
                self.last_t = now
                self.show(frame)
                if not self.writer:
                    self.status.config(text=f"{frame.shape[1]}x{frame.shape[0]}  {self.fps:.0f} FPS")
        self.after(10, self.loop)

    def show(self, frame):
        vw, vh = max(self.view.winfo_width(), 2), max(self.view.winfo_height(), 2)
        h, w = frame.shape[:2]
        s = min(vw / w, vh / h)
        img = cv2.resize(frame, (max(int(w * s), 1), max(int(h * s), 1)))
        img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        self.photo = ImageTk.PhotoImage(img)
        self.view.config(image=self.photo)

    def on_close(self):
        self.stop_camera()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
