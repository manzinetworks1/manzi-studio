"""Put the finished files where you can get them on your phone: Google Drive if set up, otherwise a GitHub Release."""
import json, mimetypes, os, urllib.parse, urllib.request
from common import http_json, secret, log


def _post_bytes(url, data, headers, method="POST"):
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=900) as r: return r.status, dict(r.headers), r.read()


# ------------------------------------------------------------------ Google Drive
def drive_ready(): return all(os.environ.get(k) for k in ("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN"))


def drive_upload(files, folder_name, parent=None):
    data = urllib.parse.urlencode({"client_id": secret("GDRIVE_CLIENT_ID"), "client_secret": secret("GDRIVE_CLIENT_SECRET"),
                                   "refresh_token": secret("GDRIVE_REFRESH_TOKEN"), "grant_type": "refresh_token"}).encode()
    _, _, body = _post_bytes("https://oauth2.googleapis.com/token", data, {"Content-Type": "application/x-www-form-urlencoded"})
    at = json.loads(body)["access_token"]; auth = {"Authorization": f"Bearer {at}"}
    meta = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    if parent: meta["parents"] = [parent]
    folder = http_json("https://www.googleapis.com/drive/v3/files?fields=id,webViewLink", meta, auth)
    links = {}
    for f in files:
        m = {"name": os.path.basename(f), "parents": [folder["id"]]}
        st, hd, _ = _post_bytes("https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id,webViewLink",
                                json.dumps(m).encode(), {**auth, "Content-Type": "application/json; charset=UTF-8",
                                                         "X-Upload-Content-Type": mimetypes.guess_type(f)[0] or "application/octet-stream"})
        loc = hd.get("Location") or hd.get("location")
        _, _, b = _post_bytes(loc, open(f, "rb").read(), {"Content-Type": mimetypes.guess_type(f)[0] or "application/octet-stream"}, "PUT")
        links[os.path.basename(f)] = json.loads(b).get("webViewLink", folder["webViewLink"]); log("  uploaded", os.path.basename(f))
    return folder["webViewLink"], links


# ------------------------------------------------------------------ GitHub Release (no extra setup)
def release_upload(files, tag, title, notes):
    repo = secret("GITHUB_REPOSITORY"); tok = secret("GITHUB_TOKEN"); api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    rel = http_json(f"{api}/repos/{repo}/releases", {"tag_name": tag, "name": title, "body": notes}, h)
    up = rel["upload_url"].split("{")[0]; links = {}
    for f in files:
        _, _, b = _post_bytes(up + "?" + urllib.parse.urlencode({"name": os.path.basename(f)}), open(f, "rb").read(),
                              {**h, "Content-Type": mimetypes.guess_type(f)[0] or "application/octet-stream"})
        links[os.path.basename(f)] = json.loads(b)["browser_download_url"]; log("  uploaded", os.path.basename(f))
    return rel["html_url"], links


def deliver(files, week, cfg):
    if drive_ready():
        log("uploading to Google Drive…"); return drive_upload(files, f"{cfg['channel']} - week {week}", cfg.get("drive_folder_id") or None)
    log("uploading to a GitHub Release…")
    return release_upload(files, f"week-{week}", f"Videos for week {week}", "Your videos for this week. See the email for the posting plan.")
