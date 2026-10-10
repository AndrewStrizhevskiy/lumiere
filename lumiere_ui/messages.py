# SPDX-License-Identifier: GPL-3.0-or-later
"""Plain-language wording for every engine code. All strings go through Qt's translation system (English is the source language)."""
from __future__ import annotations

from dataclasses import dataclass, field

from PyQt6.QtCore import QCoreApplication

from lumiere import events as ev


def tr(text: str, ctx: str = "Messages") -> str:
    return QCoreApplication.translate(ctx, text)


@dataclass
class Message:
    level: str                                   # info | warning | error | success
    title: str
    text: str
    actions: list[tuple[str, str]] = field(default_factory=list)     # (key, label)


def for_code(code: str, detail: dict | None = None) -> Message | None:
    d = detail or {}
    retry = ("retry", tr("Try again"))
    check = ("network_check", tr("Check my connection"))
    settings = ("settings", tr("Open settings"))
    if code == ev.NO_PEERS:
        return Message("warning", tr("No sources available"),
                       tr("No sources are currently available for this torrent. Try again later or check your network connection."),
                       [check, retry])
    if code == ev.NETWORK_LOST:
        return Message("warning", tr("Connection interrupted"),
                       tr("The connection was interrupted. Lumière will try to reconnect."), [check])
    if code == ev.NETWORK_RESTORED:
        return Message("success", tr("Back online"), tr("Sources are available again."))
    if code == ev.SLOW_CONNECTION:
        return Message("warning", tr("Slow connection"),
                       tr("Your connection may be too slow for uninterrupted playback. Try a lower playback position or wait for more data to buffer."),
                       [check])
    if code == ev.CACHE_FULL:
        return Message("info", tr("Making room"),
                       tr("Lumière is freeing space from older cached sections. Playback may pause briefly."))
    if code == ev.UNSUPPORTED_FILE:
        return Message("error", tr("Can't play this file"),
                       tr("This file format could not be opened. Please select a supported video file."), [("open_other", tr("Choose another file"))])
    if code == ev.PLAYER_ERROR:
        return Message("error", tr("Playback problem"), tr("The player stopped unexpectedly. Try opening the video again."), [retry])
    if code == ev.CACHE_UNSUPPORTED_FS:
        return Message("error", tr("This disk can't limit the cache"),
                       tr("A cache size limit can only be guaranteed on disks that can release space inside files, and the folder Lumière uses "
                          "can't. You can choose a folder on another drive in Settings, or play in temporary mode: it has no size limit "
                          "and its data is deleted when you close the video."),
                       [settings, ("play_temporary", tr("Play in temporary mode"))])
    if code == ev.CACHE_TOO_SMALL:
        return Message("error", tr("The cache is too small for this video"),
                       tr("The cache size set in Settings is too small to stream this video smoothly. Increase it and try again."), [settings])
    if code == ev.CACHE_DIR_NOT_MANAGED:
        return Message("error", tr("Folder already in use"),
                       tr("The cache folder already contains files that Lumière didn't create, so it won't use or change them. "
                          "Choose a different cache folder in Settings."), [settings])
    if code == ev.STORE_FAILED:
        return Message("error", tr("Streaming stopped to protect your data"),
                       tr("Lumière stopped streaming because it could not keep the downloaded data safe. Close the video and open it again. "
                          "If this keeps happening, open Diagnostics."), [("diagnostics", tr("Open diagnostics")), retry])
    if code == ev.OPEN_FAILED:
        return Message("error", tr("Couldn't open this torrent"),
                       tr("The torrent file or link could not be read, or no one is sharing its details right now. Check that it is complete and try again."),
                       [check, retry])
    if code in ("NO_LIBTORRENT", "NO_MPV"):
        return Message("error", tr("A required component is missing"),
                       tr("Lumière needs the system packages python3-libtorrent and python3-mpv. Install them and start the app again."))
    if code == "LOW_DISK_SPACE":
        return Message("warning", tr("Low disk space"), tr("There is less than 1 GB free where Lumière stores its cache."), [settings])
    if code == "CACHE_DIR_UNUSABLE":
        return Message("error", tr("Can't use the cache folder"), tr("Lumière can't write to its cache folder. Choose another folder in Settings."), [settings])
    return None


VERDICTS = {                                   # network check results, each tagged by how sure we are
    "udp_dropped": ("confirmed", "Outgoing UDP traffic gets no answer on this connection (even DNS over UDP). Peer discovery through DHT and UDP trackers cannot work here."),
    "udp_bittorrent_no_answer": ("confirmed", "DNS over UDP works, but BitTorrent's peer-discovery messages get no answer on this connection."),
    "protocol_filtering_possible": ("hypothesis", "This could be filtering of BitTorrent traffic by the network or the VPN, but this test cannot prove who is responsible or why."),
    "udp_partial": ("observed", "Some peer-discovery servers answered and some didn't. Public servers also go offline, so this alone doesn't show a restriction."),
    "udp_ok": ("observed", "Peer-discovery servers answered. No UDP restriction was seen in this test."),
    "tcp_ports_unreachable": ("observed", "Some TCP ports used by BitTorrent could not be reached."),
    "no_tcp_port_blocking": ("confirmed", "TCP connections on the ports BitTorrent commonly uses work."),
    "vpn_in_path": ("observed", "Your traffic goes through a VPN or tunnel. That can slow BitTorrent down or limit peer discovery."),
    "isp_throttling": ("not_measured", "Whether your provider limits your speed was not measured."),
    "inbound_reachability": ("not_measured", "Whether other people can connect to you was not measured."),
}
KIND_LABEL = {"confirmed": "Confirmed", "observed": "Observed", "hypothesis": "Possible", "not_measured": "Not measured"}
