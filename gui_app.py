import os
import sys
import subprocess
import tkinter as tk
from tkinter import font as tkfont


def get_desktop_path():
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes
            CSIDL_DESKTOP = 0
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(0, CSIDL_DESKTOP, 0, 0, buf) == 0:
                path = buf.value
                if os.path.isdir(path):
                    return path
        except Exception:
            pass
        profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        for candidate in [
            os.path.join(profile, "OneDrive", "Desktop"),
            os.path.join(profile, "Desktop"),
        ]:
            if os.path.isdir(candidate):
                return candidate
    return os.path.join(os.path.expanduser("~"), "Desktop")


def list_desktop_apps(max_items=24):
    desktop = get_desktop_path()
    if not os.path.isdir(desktop):
        return []

    allowed = (".lnk", ".exe", ".bat", ".cmd", ".url")
    items = []
    for name in sorted(os.listdir(desktop)):
        full = os.path.join(desktop, name)
        if os.path.isfile(full) and name.lower().endswith(allowed):
            items.append(full)
    return items[:max_items]


def launch_app(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)
        else:
            subprocess.Popen([path])
    except Exception as e:
        print(f"Failed to open {path}: {e}")


def submit_entry(entry_widget):
    text = entry_widget.get().strip()
    if text:
        print(text)
        entry_widget.delete(0, tk.END)


def on_enter_key(event):
    submit_entry(event.widget)


def main():
    root = tk.Tk()
    root.title("Desktop + Console")
    root.configure(bg="#181818")
    root.geometry("900x520")
    root.minsize(700, 420)

    root.update_idletasks()
    x = (root.winfo_screenwidth() // 2) - (900 // 2)
    y = (root.winfo_screenheight() // 2) - (520 // 2)
    root.geometry(f"900x520+{x}+{y}")

    title_font = tkfont.Font(size=16, weight="bold")
    app_font = tkfont.Font(size=11)
    input_font = tkfont.Font(size=14)
    button_font = tkfont.Font(size=12)

    main_frame = tk.Frame(root, bg="#181818")
    main_frame.pack(fill="both", expand=True, padx=20, pady=16)

    desktop_frame = tk.Frame(main_frame, bg="#181818")
    desktop_frame.pack(fill="both", expand=True)

    title_label = tk.Label(
        desktop_frame,
        text="Desktop Applications",
        bg="#181818",
        fg="#ffffff",
        font=title_font,
        anchor="w",
    )
    title_label.pack(fill="x", pady=(0, 8))

    apps_frame = tk.Frame(desktop_frame, bg="#181818")
    apps_frame.pack(fill="both", expand=True)

    apps = list_desktop_apps(max_items=24)
    cols = 4
    for idx, path in enumerate(apps):
        name = os.path.basename(path)
        base, _ext = os.path.splitext(name)
        label_text = base or name

        btn = tk.Button(
            apps_frame,
            text=label_text,
            width=18,
            height=3,
            wraplength=120,
            justify="center",
            bg="#303030",
            fg="#e0e0e0",
            activebackground="#404040",
            activeforeground="#ffffff",
            relief="flat",
            borderwidth=1,
            highlightthickness=0,
            font=app_font,
            command=lambda p=path: launch_app(p),
        )
        r = idx // cols
        c = idx % cols
        btn.grid(row=r, column=c, padx=10, pady=10, sticky="n")

    if not apps:
        empty_label = tk.Label(
            apps_frame,
            text=f"No .lnk / .exe / .url shortcuts found.\nReading from: {get_desktop_path()}",
            bg="#181818",
            fg="#aaaaaa",
            font=app_font,
            justify="left",
        )
        empty_label.pack(pady=40, anchor="w")

    bottom_frame = tk.Frame(main_frame, bg="#181818")
    bottom_frame.pack(fill="x", pady=(10, 0))

    entry = tk.Entry(
        bottom_frame,
        width=50,
        font=input_font,
        bg="#404040",
        fg="#e0e0e0",
        insertbackground="#e0e0e0",
        relief="flat",
        borderwidth=0,
        highlightbackground="#ffffff",
        highlightthickness=1,
    )
    entry.pack(side="left", padx=(0, 10), pady=(0, 2), ipady=8)
    entry.bind("<Return>", on_enter_key)
    entry.focus_set()

    enter_btn = tk.Button(
        bottom_frame,
        text="Enter",
        font=button_font,
        bg="#404040",
        fg="#e0e0e0",
        activebackground="#505050",
        activeforeground="#e0e0e0",
        relief="flat",
        borderwidth=1,
        highlightthickness=0,
        command=lambda: submit_entry(entry),
    )
    enter_btn.pack(side="left", pady=(0, 2))

    root.mainloop()


if __name__ == "__main__":
    main()