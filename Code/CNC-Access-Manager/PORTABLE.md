# Moving CNC Access Manager to the school computer (one-click)

You have two ways to run it. Neither requires typing commands.

---

## Option A — copy the folder (needs Python on the school PC)

1. Copy the whole `cnc` folder to the school computer.
2. Double-click **`start.bat`**.
   - A console window opens and the browser opens to `http://localhost:8000`
     automatically. Login `admin` / `admin`.
   - Keep the console window open; close it to stop.

If Python is **not** installed on the school PC, use Option B instead.

---

## Option B — build a standalone .exe (NO Python needed on the school PC)  ★ recommended for school

Do this once on your home PC (which has Python):

1. Double-click **`build_exe.bat`**.
   - It installs PyInstaller, builds the app, and creates a **`portable`** folder
     containing `CNC-Access-Manager.exe` + `index.html` + `style.css` + `app.js`
     (+ `cnc.db`).
2. Copy the whole **`portable`** folder to the school computer (USB stick or cloud).
3. On the school computer, just **double-click `CNC-Access-Manager.exe`**.
   - The database and web app run from that one folder; the browser opens
     automatically. No Python, no commands.

### First-run prompts on the school PC (normal)
- **SmartScreen** ("Windows protected your PC") → click **More info → Run anyway**
  (it's your own program, unsigned).
- **Windows Firewall** may ask to allow the app on the network → allow it (needed
  so the on-machine Pico can reach the server; for localhost-only use you can decline).

---

## Testing the Scan flow without a card reader (no commands)

1. Start the app, log in, open the **System** tab.
2. Under **Testing without hardware**, keep `A388DB1C` (or type any UID) and click
   **Simulate tap**.
3. Open **Users → Add user** and press **Scan** within ~12 s — the Card field
   fills with that UID. Enter a PIN, Save.

(That `curl` command from earlier fails in PowerShell because `curl` there is an
alias for `Invoke-WebRequest`. You don't need it anymore — use the Simulate tap
button. If you ever do want the command line, use `curl.exe` instead of `curl`.)

---

## Notes
- The database is `cnc.db` in the same folder as the app; back it up to keep your
  registered users. Deleting it makes the app re-create the demo users.
- To change the admin password, edit `ADMIN_PASS` in `server.py` (Option A) or
  rebuild the exe after editing it (Option B).
