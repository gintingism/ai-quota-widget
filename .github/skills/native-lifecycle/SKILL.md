# Native lifecycle

Keep tray callbacks and worker callbacks out of Tk operations. Marshal updates
with `after`, stop fetchers before replacing them, and use generation guards so
late worker results cannot update a destroyed or replaced window.
