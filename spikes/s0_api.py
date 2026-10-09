# SPDX-License-Identifier: GPL-3.0-or-later
"""Spike 0: print the real libtorrent Python API (docstring signatures) on this machine."""
import libtorrent as lt
print("libtorrent", lt.__version__)
def sig(obj, name):
    f = getattr(obj, name, None)
    if f is None:
        print(f"  {name}: MISSING"); return
    doc = (f.__doc__ or "").strip().splitlines()
    print(f"  {name}: " + " | ".join(l.strip() for l in doc[:3] if l.strip())[:230])
for cls, names in [
    (lt, ["session", "parse_magnet_uri", "add_torrent_params", "torrent_info", "create_torrent", "set_piece_hashes", "read_resume_data", "write_resume_data_buf", "write_resume_data", "bencode", "bdecode"]),
    (lt.session, ["add_torrent", "remove_torrent", "pop_alerts", "set_alert_notify", "apply_settings", "post_torrent_updates", "wait_for_alert", "get_settings"]),
    (lt.torrent_info, ["files", "piece_length", "piece_size", "num_pieces", "map_file", "map_block", "info_hash", "name", "total_size", "hash_for_piece"]),
    (lt.file_storage, ["file_offset", "file_size", "file_path", "num_files", "piece_size", "num_pieces", "file_name", "total_size"]),
    (lt.torrent_handle, ["piece_priority", "prioritize_pieces", "get_piece_priorities", "set_piece_deadline", "reset_piece_deadline", "clear_piece_deadlines", "have_piece", "status", "read_piece", "clear_piece", "file_priority", "prioritize_files", "save_resume_data", "force_recheck", "force_reannounce", "set_flags", "unset_flags", "connect_peer", "set_upload_limit", "set_download_limit", "torrent_file", "get_piece_priorities", "piece_availability", "flags", "pause", "resume", "http_seed_removal" ]),
]:
    print(cls.__name__ if hasattr(cls, "__name__") else cls)
    for n in names: sig(cls, n)
print("status flags:", [x for x in dir(lt.torrent_handle) if "query" in x])
print("torrent_status.pieces:", hasattr(lt.torrent_status, "pieces"))
print("alerts:", sorted(a for a in dir(lt) if a.endswith("_alert") and any(k in a for k in ("piece", "read", "metadata", "resume", "torrent_error", "file_error", "state_changed", "hash", "torrent_checked", "peer_ban", "stats"))))
print("disk io ctors:", [x for x in dir(lt) if "disk" in x or "storage" in x])
print("torrent_flags:", [x for x in dir(lt.torrent_flags) if not x.startswith("_")])
print("save_resume flags:", [x for x in dir(lt.save_resume_flags_t) if not x.startswith("_")] if hasattr(lt, "save_resume_flags_t") else "n/a")
print("deadline_flags:", [x for x in dir(lt.deadline_flags_t) if not x.startswith("_")] if hasattr(lt, "deadline_flags_t") else [x for x in dir(lt) if "deadline" in x])
print("atp fields:", [x for x in dir(lt.add_torrent_params) if not x.startswith("_")])
