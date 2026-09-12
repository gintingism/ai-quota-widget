# AI Quota Widget (Windows)

Widget desktop ringan untuk memantau rolling quota **5 jam** dan weekly reset melalui floating window serta Windows System Tray.

## Fitur

- Frameless, semi-transparan, dapat di-drag, dan opsi Always on Top.
- Tombol `Triggered Session` memulai ulang countdown 5 jam.
- Weekly reset dengan hari dan jam lokal yang dapat diubah.
- Tray menu: Open, Settings, Force Reset Timer, Exit.
- Configurable realtime quota endpoint with Bearer/session token and cookies,
  background polling, normalized Gemini/Claude quota data, and offline fallback.
- Docked mode aligns to the Windows work area above the taskbar; clicking the
  summary expands model details. Right-clicking the widget opens settings.
- Posisi, warna aksen, preferensi Always on Top, dan timer tersimpan di `%APPDATA%\AIQuotaWidget\config.json`.
- Timer memakai Unix timestamp sehingga tetap benar setelah sleep/hibernasi.

## Menjalankan dari source

```powershell
cd ai_quota_widget
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Salin `config.example.json` menjadi `config.json` hanya jika ingin menyiapkan nilai awal manual. Isi `quota_endpoint` dengan endpoint status kuota yang memang Anda miliki/diizinkan untuk akses, lalu masukkan token/cookie melalui Settings. Secara default file aktif dibuat otomatis di `%APPDATA%\AIQuotaWidget`. Token disimpan lokal dalam file JSON; jangan membagikan file tersebut.

## Build executable Windows (opsional)

```powershell
python -m pip install pyinstaller
pyinstaller --noconsole --onefile --name AIQuotaWidget main.py
```

Executable berada di `dist\AIQuotaWidget.exe`.
