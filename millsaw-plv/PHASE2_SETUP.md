# Phase 2 — Remote PLV transfer over FTP

This guide covers installing the saw-side FTP server (Windows 7
compatible) and configuring the IT-side app to push PLVs to it.

---

## Architecture (one-pager)

```
+-------------------+        FTP / TCP         +---------------------+
|   IT machine      |  ───────────────────▶   |   Saw PC (Win 7)    |
|  Mill Saw GUI     |   port 2121 (control)   |  mill_saw_ftp.py    |
|  ftplib (stdlib)  |   ports 50000-50050     |  pyftpdlib server   |
|                   |   (passive data)        |                     |
|                   |                         |  Drop folder:       |
|                   |                         |  C:\iLENIA\Cn\      |
|                   |                         |     Troptim\PLV    |
+-------------------+                         +---------------------+
```

The IT-side app uses Python's built-in `ftplib`. The saw side runs a
small Python FTP server (`mill_saw_ftp.py`) that auto-starts at user
login. Any other FTP server (FileZilla Server, IIS FTP) works too — the
client is standard FTP.

---

## Saw-side install (Windows 7)

You only do this once per saw PC.

### 1. Install Python 3.8 (last version that supports Windows 7)

1. Download <https://www.python.org/downloads/release/python-3810/> →
   **Windows installer (64-bit)**.
2. Run the installer. **Tick "Add python.exe to PATH"** at the bottom of
   the first screen, then click **Install Now**.
3. Reboot (recommended after Python install on Win 7).

### 2. Run the listener installer

1. Copy the entire `saw_listener\` folder from this project onto the saw
   PC (USB stick or shared folder is fine).
2. Right-click **`install_ftp_listener.bat`** and choose **Run as
   administrator** (admin is only needed to add the Windows Firewall
   rules; the rest works as a normal user).
3. The script will:
   - `pip install pyftpdlib`
   - copy files into `C:\MillSawFTP\`
   - create `C:\iLENIA\Cn\Troptim\PLV\`
   - register `HKCU\…\Run\MillSawFTP` so the server **auto-starts at
     every user login**
   - open ports 2121 and 50000–50050 in Windows Firewall
   - start the server immediately

You'll see "Install complete" and a console window will appear running
the FTP server.

### 3. Change the default password (important)

The listener refuses to start while the password is still `changeme`.

Open `C:\MillSawFTP\ftp_server.ini` in Notepad and edit:

```ini
[user]
username = millsaw
password = changeme    ← CHANGE THIS
```

Optional — restrict who can connect by IP:

```ini
[security]
allowed_ips = 192.0.2.50
```

(Comma-separate multiple IPs. Empty = anyone with the password can
upload.)

After saving, restart the listener:
- Easy way: log out / log back in.
- Or: kill `pythonw.exe` in Task Manager, then double-click
  `C:\MillSawFTP\mill_saw_ftp.py`.

### 4. Verify the server is reachable

From the IT machine, in PowerShell:

```powershell
Test-NetConnection -ComputerName <SAW_IP> -Port 2121
```

The line `TcpTestSucceeded : True` means you're good. If it's `False`,
double-check Windows Firewall on the saw PC and any VLAN/router ACL
between the two networks.

---

## IT-side configuration

The new build of the GUI has two new buttons in the top bar:

- **Manage Saws…** — add / edit / remove saw PCs and run a Test
  Connection button against each.
- **Send to Saw…** — pick a saw, pick one or more PLV files from the
  current job, watch a progress bar.

### Adding your first saw

1. Open the app (`python run.py`).
2. Click **Manage Saws…** → **Add…**.
3. Fill in:
   - **Name**: a label, e.g. `ChopSaw1`.
   - **Host**: the saw PC's IP or DNS name (e.g. `192.0.2.50`).
   - **Port**: `2121` (default; matches the listener's `ftp_server.ini`).
   - **Username** / **Password**: same as you set in `ftp_server.ini`.
   - **Remote dir**: `/` (the FTP user is already chrooted into the drop
     folder, so root means the drop folder itself).
   - **Passive mode**: leave checked unless you have a specific reason.
4. Click **OK**, then **Test connection** in the manage dialog. You
   should see "Connected. Remote dir = /".
5. **Close** to save.

The list is stored in `saws.json` next to the project folder.

### Sending a PLV

1. Pick the job from the list and load it.
2. Make sure you've **Generated PLV file(s)** for that job.
3. Click **Send to Saw…**.
4. Pick the saw and one or more PLV files (Ctrl-click for multiple).
5. **Upload**. The progress bar fills up; on success you get
   "Uploaded N file(s)".

---

## Troubleshooting

**"FTP transfer failed: 425 Can't open data connection"**
The passive data ports (50000–50050) are blocked. On the saw PC, re-run
`install_ftp_listener.bat` as administrator, or manually allow that
port range through Windows Firewall.

**"FTP transfer failed: 530 Authentication failed"**
Username/password mismatch. The values in **Manage Saws…** must match
`[user]` in `ftp_server.ini` on the saw exactly (case-sensitive).

**"Connection refused"**
The listener isn't running on the saw PC. Open Task Manager →
**Details** tab and look for `pythonw.exe`. If it's not there, log out
and log back in (the Run-key entry starts the listener at login), or
double-click `C:\MillSawFTP\mill_saw_ftp.py` to start it manually.

**"Temporary failure in name resolution"**
The Host you typed doesn't resolve. Use the IP address instead of a
hostname.

**"No route to host" between two VLANs**
This is a network layer issue, not the app. Ask whoever runs the
firewall/router to allow TCP `2121` and `50000-50050` from the IT
subnet to the saw subnet.

**Files arrive but TROPTIM doesn't see them**
Check that the drop folder in `ftp_server.ini` matches the folder
TROPTIM is configured to monitor. Default is `C:\iLENIA\Cn\Troptim\PLV`.

---

## Uninstalling on the saw side

Run `uninstall_ftp_listener.bat` on the saw PC. It removes the Run-key
auto-start, deletes the firewall rules, and stops a currently-running
listener. The drop folder and any received PLVs are **left intact**.

---

## Why FTP and not a custom protocol

- It's a 35-year-old standard. Anything that needs to talk to it
  already exists (FileZilla, WinSCP, native Windows Explorer).
- `ftplib` ships with Python — no new dependencies on the IT side.
- Easy to swap in **FileZilla Server** later if you ever want a GUI on
  the saw side; the client doesn't change.
- Cross-VLAN / firewall-friendly: only one TCP port to open for control
  + a small range for passive data.
