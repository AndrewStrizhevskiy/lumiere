# Installing Lumière

Supported and tested: **Ubuntu 24.04 LTS, GNOME on Wayland, Python 3.12**. Other distributions with the same libraries should work but are untested.

## System dependencies

| package (apt) | why |
|---|---|
| `python3-libtorrent` (2.0.x) | BitTorrent engine (the Python binding is not on PyPI in a usable form; use the distribution package) |
| `python3-pyqt6`, `python3-pyqt6.qtsvg` | desktop app (Qt 6) |
| `python3-mpv`, `libmpv2` | embedded player |
| `mpv` | used by the command line tool; also useful for checking codecs |
| `ffmpeg` | **tests only** |

```bash
sudo apt install python3-libtorrent python3-pyqt6 python3-pyqt6.qtsvg python3-mpv libmpv2 mpv
```

Optional: the *Inter* font (`fonts-inter`) for the intended look; Lumière falls back to Cantarell / Noto Sans / DejaVu.

## Install

```bash
git clone https://github.com/AndrewStrizhevskiy/lumiere.git lumiere
cd lumiere
./packaging/install.sh --check     # lists missing packages and the exact paths it would write
./packaging/install.sh
```

The installer needs no root, no network and no pip. It copies the program into `~/.local/share/lumiere/app/` and creates only:

| path | what |
|---|---|
| `~/.local/share/lumiere/app/` | the two Python packages |
| `~/.local/bin/lumiere`, `~/.local/bin/lumiere-gui` | launchers (it refuses to overwrite a file it did not create) |
| `~/.local/bin/kino-stream`, `~/.local/bin/kino-stream-gui` | compatibility launchers for the former command names (they only run the launchers above; left alone if you have a file of that name that is not ours) |
| `~/.local/share/applications/lumiere.desktop` | application-menu entry |
| `~/.local/share/icons/hicolor/scalable/apps/lumiere.svg` | icon |

Install paths (your home folder, `XDG_DATA_HOME`, `LUMIERE_BIN`) may contain spaces and most special characters; the installer quotes them correctly for the launcher script
and the desktop entry. Two cases are refused with an explanation instead of installing a launcher that would silently not start: a `%` in the launcher directory (valid in the
specification, but GNOME's launcher library rejects it; choose another directory with `LUMIERE_BIN=<dir>`) and control characters such as tabs or newlines in any path.

Then start **Lumière** from the application menu (you may have to log out and in once if the menu does not show it) or run `lumiere-gui`.
Without installing, you can run it from the checkout: `python3 -m lumiere_ui` (app) and `./bin/lumiere` (CLI).

### `.torrent` files and magnet links

The launcher *declares* that it can open `.torrent` files and `magnet:` links, so it appears under "Open with…". It does **not** change
your default applications (for example qBittorrent keeps handling magnet links). To make Lumière the default yourself:

```bash
xdg-mime default lumiere.desktop application/x-bittorrent x-scheme-handler/magnet
```

If Lumière is already running, opening a file or link from the desktop hands it to the running window (two instances are never
started, because they must not share a cache).

## Upgrading from the former name (`kino-stream`)
Versions up to 0.3.0-rc.1 were called *Kino Stream* (commands `kino-stream`, `kino-stream-gui`, folders `kino-stream`). Run `./packaging/install.sh` from the new checkout:
* the old application folder (`~/.local/share/kino-stream/app`), menu entry (`kino-stream.desktop`) and icon are **removed** (only if the installer created them);
* `~/.local/bin/kino-stream` and `kino-stream-gui` become small **compatibility launchers** that run `lumiere` / `lumiere-gui` (a file with that name that this installer did not create is left alone);
* your **settings, history and cache are not touched by the installer**: the application moves `~/.config/kino-stream`, `~/.local/state/kino-stream` and `~/.cache/kino-stream` to the new names the first time it starts, recoverably (details: [FILES_AND_DATA.md](FILES_AND_DATA.md#migration-from-the-former-name)).
The old `KINO_STREAM_THEME` and `KINO_REDUCE_MOTION` environment variables are still honoured when the new ones (`LUMIERE_THEME`, `LUMIERE_REDUCE_MOTION`) are not set; the installer variable is now `LUMIERE_BIN`.

## Uninstall (does not touch any other application or system setting)

```bash
./packaging/uninstall.sh --dry-run        # shows what would be removed
./packaging/uninstall.sh                  # removes the program, launchers, menu entry, icon; KEEPS your settings, history and cache data
./packaging/uninstall.sh --purge-data     # additionally removes ~/.config/lumiere, ~/.local/state/lumiere, ~/.cache/lumiere
```

`--purge-data` never deletes a custom cache folder you chose in Settings; it prints its location so you can remove it yourself.
If you made Lumière your default for `.torrent`/magnet with `xdg-mime`, set another default again afterwards
(for example `xdg-mime default <other-app>.desktop x-scheme-handler/magnet`).
The APT packages are not removed (other programs may use them): `sudo apt remove python3-mpv python3-pyqt6.qtsvg` if you want them gone.
See [FILES_AND_DATA.md](FILES_AND_DATA.md) for everything the program can create.

## Updating

Pull the new version and run `./packaging/install.sh` again; it replaces its own files only.
