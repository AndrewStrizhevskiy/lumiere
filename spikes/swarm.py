"""Local test swarm helpers (no DHT/trackers/internet): a seeder session and leecher sessions on 127.0.0.1."""
import os, time, hashlib
import libtorrent as lt


def make_payload(path, size, seed=1):
    """Deterministic pseudo-random file (our own data, nothing copyrighted)."""
    import random
    r = random.Random(seed)
    with open(path, "wb") as f:
        left = size
        while left:
            n = min(1 << 20, left)
            f.write(r.randbytes(n)); left -= n


def make_torrent(src_dir, name, piece_length=256 * 1024):
    fs = lt.file_storage()
    lt.add_files(fs, os.path.join(src_dir, name))
    ct = lt.create_torrent(fs, piece_length)
    lt.set_piece_hashes(ct, src_dir)
    return lt.torrent_info(lt.bencode(ct.generate()))


def new_session(port, upload_limit=0, download_limit=0, **extra):
    s = {
        "listen_interfaces": f"127.0.0.1:{port}", "enable_dht": False, "enable_lsd": False,
        "enable_upnp": False, "enable_natpmp": False, "announce_to_all_trackers": False,
        "ignore_limits_on_local_network": False, "upload_rate_limit": upload_limit,
        "download_rate_limit": download_limit, "allow_multiple_connections_per_ip": True,
        "alert_mask": lt.alert.category_t.error_notification | lt.alert.category_t.status_notification | lt.alert.category_t.piece_progress_notification, "alert_queue_size": 20000,
    }
    s.update(extra)
    return lt.session(s)


def add(sess, ti, save_path, **kw):
    p = lt.add_torrent_params()
    p.ti = ti
    p.save_path = save_path
    for k, v in kw.items():
        setattr(p, k, v)
    return sess.add_torrent(p)


def wait_until(cond, timeout, step=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


def sha(path, a=0, n=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        f.seek(a); left = n
        while left is None or left > 0:
            c = f.read(1 << 20 if left is None else min(1 << 20, left))
            if not c: break
            h.update(c); left = None if left is None else left - len(c)
    return h.hexdigest()
