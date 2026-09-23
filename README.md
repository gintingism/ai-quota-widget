# AI Quota Widget (Windows)

Widget desktop ringan untuk memantau rolling quota **5 jam** dan weekly reset melalui floating window serta Windows System Tray.

## Fitur

- Frameless, semi-transparan, dapat di-drag, dan opsi Always on Top.
- Tombol `Triggered Session` memulai ulang countdown 5 jam.
- Weekly reset dengan hari dan jam lokal yang dapat diubah.
- Tray menu: Open, Settings, Force Reset Timer, Exit.
- Multi-provider monitoring for Google Antigravity and GitHub Copilot with
  independent credentials, intervals, parsing, and offline fallback.
- Antigravity accepts a user-configured endpoint, session token, and cookies.
  GitHub Copilot accepts a GitHub token and sends `Editor-Version` to the
  configured Copilot endpoint. The default internal user endpoint is
  undocumented and may change; if it or a configured endpoint only exposes
  identity/token data, the widget shows `--%` and explains that quota is
  unavailable. GitHub's documented REST API exposes Copilot usage metrics for
  organizations and enterprises, not an individual account's live remaining
  quota.
- Docked mode aligns to the Windows work area above the taskbar; clicking the
  summary expands model details. Right-clicking the widget opens settings.
- Posisi, warna aksen, preferensi Always on Top, dan timer tersimpan di `%APPDATA%\AIQuotaWidget\config.json`.
- Fluent/glass-style dark UI dengan progress pill berwarna dinamis, status dot,
  panel detail dua kartu, tombol Refresh/Settings, dan resize expand yang halus.
- Timer memakai Unix timestamp sehingga tetap benar setelah sleep/hibernasi.

## Menjalankan dari source

```powershell
cd ai_quota_widget
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Saat startup, aplikasi otomatis mencoba mengambil token GitHub dari `gh auth token`,
lalu fallback ke `%LOCALAPPDATA%\github-copilot\hosts.json`. Token hanya disimpan
ke `%APPDATA%\AIQuotaWidget\config.json` dan tidak pernah dicetak. Untuk menjalankan
deteksi sekali jalan tanpa membuka widget:

```powershell
python auto_configure_github.py
```

Script tidak menimpa token yang sudah ada. Untuk mengambil ulang secara eksplisit,
jalankan dari Python:

```powershell
python -c "from config_manager import ConfigManager; ConfigManager().auto_configure_github_token(force=True)"
```

Salin `config.example.json` menjadi `config.json` hanya jika ingin menyiapkan nilai awal manual. Masukkan token melalui Settings. Konfigurasi flat lama (`quota_endpoint`, `session_token`, `cookies`, dan `poll_interval_seconds`) dimigrasikan otomatis ke `antigravity` saat dibaca. Secara default file aktif dibuat otomatis di `%APPDATA%\AIQuotaWidget`. Token disimpan lokal dalam file JSON; jangan membagikan file tersebut.

## Build executable Windows (opsional)

```powershell
python -m pip install -r requirements.txt
python build.py
```

`build.py` membuat icon `ai_quota_widget.ico`, mengaktifkan `--onefile`,
`--noconsole`, `--collect-all customtkinter`, dan menghasilkan
`dist\AIQuotaWidget.exe`. Konfigurasi runtime tetap ditulis ke
`%APPDATA%\AIQuotaWidget\config.json`, bukan ke folder bundle sementara.
