from flask import Flask, request, jsonify, send_file, abort
from redis import Redis
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import lzma
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
import zipfile

app = Flask(__name__)

RELEASE_NAME = os.environ.get("RELEASE_NAME", "stable")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
CACHE_DIR = os.environ.get("CACHE_DIR", "/cache")
GPG_KEY_ID = os.environ.get("GPG_KEY_ID", "DebZip Signing Key")
MAX_PACKAGE_COUNT = int(os.environ.get("MAX_PACKAGE_COUNT", "500"))
MAX_TOTAL_BYTES = int(os.environ.get("MAX_TOTAL_BYTES", str(2 * 1024 * 1024 * 1024)))

PACKAGE_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")
JOB_RE = re.compile(r"^[a-f0-9-]{8,64}$")
ALLOWED_ARCHES = {"amd64", "i386", "arm64", "armhf", "armel", "ppc64el", "s390x", "riscv64"}
APT_URI_RE = re.compile(r"'(?P<url>https?://[^']+)'\s+(?P<filename>\S+)\s+(?P<size>\d+)\s+(?P<checksum>\S+)")
DEB_NAME_RE = re.compile(r"^(?P<name>.+)_(?P<version>.+)_(?P<arch>[^_]+)\.deb$")

redis_conn = Redis.from_url(REDIS_URL)

CACHE_TTL = {
    "oldoldstable": timedelta(days=30),
    "oldstable": timedelta(days=30),
    "stable": timedelta(days=14),
    "testing": timedelta(days=1),
    "sid": timedelta(hours=6),
}

active_jobs_lock = threading.Lock()
active_jobs = 0
MAX_CONCURRENT_JOBS = int(os.environ.get("MAX_CONCURRENT_JOBS", "2"))


def now_utc():
    return datetime.now(timezone.utc)


def human_size(num):
    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} PiB"


def run(cmd, cwd=None, check=True):
    result = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def apt_update_if_needed():
    stamp = f"/tmp/debzip-apt-update-{RELEASE_NAME}.stamp"
    if os.path.exists(stamp) and time.time() - os.path.getmtime(stamp) < 3600:
        return
    run(["apt-get", "update"])
    with open(stamp, "w") as f:
        f.write(str(time.time()))


def validate_package_arch(package, arch):
    if not PACKAGE_RE.match(package):
        abort(400, "Invalid package name")
    if arch not in ALLOWED_ARCHES:
        abort(400, "Invalid architecture")


def resolve_with_apt(package, arch):
    apt_update_if_needed()
    with tempfile.TemporaryDirectory() as tmp:
        status_file = os.path.join(tmp, "status")
        open(status_file, "w").close()
        cmd = [
            "apt-get",
            "-o", f"APT::Architecture={arch}",
            "-o", f"APT::Architectures={arch}",
            "-o", f"Dir::State::status={status_file}",
            "-o", "Debug::NoLocking=1",
            "--print-uris",
            "--yes",
            "--reinstall",
            "install",
            package,
        ]
        output = run(cmd)

    packages = []
    for line in output.splitlines():
        m = APT_URI_RE.search(line)
        if not m:
            continue
        filename = m.group("filename")
        nm = DEB_NAME_RE.match(filename)
        packages.append({
            "name": nm.group("name") if nm else filename,
            "version": nm.group("version") if nm else "",
            "architecture": nm.group("arch") if nm else arch,
            "filename": filename,
            "url": m.group("url"),
            "size": int(m.group("size")),
            "apt_checksum": m.group("checksum"),
        })

    packages = sorted({p["filename"]: p for p in packages}.values(), key=lambda p: p["filename"])
    if not packages:
        raise RuntimeError("No downloadable packages found. Check package name, release, and architecture.")
    if len(packages) > MAX_PACKAGE_COUNT:
        raise RuntimeError(f"Dependency tree too large: {len(packages)} packages > {MAX_PACKAGE_COUNT}")
    total = sum(p["size"] for p in packages)
    if total > MAX_TOTAL_BYTES:
        raise RuntimeError(f"Download too large: {human_size(total)} > {human_size(MAX_TOTAL_BYTES)}")
    return packages


def cache_paths(release, arch, package, packages):
    resolver_data = json.dumps({"release": release, "arch": arch, "package": package, "packages": packages}, sort_keys=True)
    h = hashlib.sha256(resolver_data.encode()).hexdigest()
    d = os.path.join(CACHE_DIR, release, arch, package, h)
    return d, os.path.join(d, f"{package}-{release}-{arch}-dependencies.zip"), os.path.join(d, "metadata.json")


def cache_valid(meta_path, zip_path):
    if not os.path.exists(meta_path) or not os.path.exists(zip_path):
        return False
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return now_utc() < datetime.fromisoformat(meta["expires_at"])
    except Exception:
        return False


def update_job(job_id, **fields):
    raw = redis_conn.get(f"debzip:job:{job_id}")
    data = json.loads(raw) if raw else {}
    data.update(fields)
    data["updated_at"] = now_utc().isoformat()
    redis_conn.setex(f"debzip:job:{job_id}", 86400, json.dumps(data))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(url, dest):
    with urllib.request.urlopen(url, timeout=300) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def sign_manifest(manifest_path):
    sig_path = manifest_path + ".asc"
    try:
        run(["gpg", "--batch", "--yes", "--armor", "--detach-sign", "--local-user", GPG_KEY_ID, "--output", sig_path, manifest_path])
    except Exception as exc:
        with open(sig_path, "w", encoding="utf-8") as f:
            f.write(f"Manifest was not signed. Configure a GPG private key. Error: {exc}\n")
    return sig_path


def build_zip_job(job_id, release, arch, package):
    global active_jobs
    with active_jobs_lock:
        if active_jobs >= MAX_CONCURRENT_JOBS:
            update_job(job_id, status="failed", progress=100, message="Too many active jobs on this worker. Try again later.")
            return
        active_jobs += 1

    tmp = None
    try:
        update_job(job_id, status="running", progress=1, message="Resolving dependencies")
        packages = resolve_with_apt(package, arch)
        cache_dir, zip_path, meta_path = cache_paths(release, arch, package, packages)
        if cache_valid(meta_path, zip_path):
            update_job(job_id, status="finished", progress=100, message="ZIP served from cache", zip_path=zip_path)
            return

        os.makedirs(cache_dir, exist_ok=True)
        tmp = tempfile.mkdtemp(prefix="debzip-")
        pkg_dir = os.path.join(tmp, "packages")
        os.makedirs(pkg_dir)
        manifest_items = []

        for idx, pkg in enumerate(packages, start=1):
            update_job(job_id, progress=int(5 + idx / max(len(packages), 1) * 75), message=f"Downloading {pkg['filename']}")
            dest = os.path.join(pkg_dir, pkg["filename"])
            download_file(pkg["url"], dest)
            pkg["sha256"] = sha256_file(dest)
            manifest_items.append(pkg)

        update_job(job_id, progress=85, message="Writing manifest")
        manifest_path = os.path.join(tmp, "MANIFEST.txt")
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write("DebZip Manifest\n===============\n\n")
            f.write(f"Requested package: {package}\n")
            f.write(f"Debian release: {release}\n")
            f.write(f"Architecture: {arch}\n")
            f.write(f"Created at: {now_utc().isoformat()}\n")
            f.write(f"Package count: {len(packages)}\n")
            f.write(f"Total download size: {sum(p['size'] for p in packages)} bytes\n\n")
            f.write("Packages:\n")
            for p in manifest_items:
                f.write(f"- {p['filename']}\n")
                f.write(f"  Name: {p.get('name','')}\n")
                f.write(f"  Version: {p.get('version','')}\n")
                f.write(f"  Architecture: {p.get('architecture','')}\n")
                f.write(f"  Size: {p.get('size','')}\n")
                f.write(f"  SHA256: {p.get('sha256','')}\n")
                f.write(f"  URL: {p.get('url','')}\n")

        sig_path = sign_manifest(manifest_path)
        update_job(job_id, progress=92, message="Creating ZIP")
        tmp_zip = zip_path + ".tmp"
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(manifest_path, "MANIFEST.txt")
            z.write(sig_path, "MANIFEST.txt.asc")
            for p in manifest_items:
                z.write(os.path.join(pkg_dir, p["filename"]), f"packages/{p['filename']}")
        os.replace(tmp_zip, zip_path)

        metadata = {
            "package": package,
            "release": release,
            "architecture": arch,
            "created_at": now_utc().isoformat(),
            "expires_at": (now_utc() + CACHE_TTL.get(release, timedelta(days=1))).isoformat(),
            "package_count": len(packages),
            "download_size_bytes": sum(p["size"] for p in packages),
            "zip_path": zip_path,
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        update_job(job_id, status="finished", progress=100, message="ZIP ready", zip_path=zip_path)
    except Exception as exc:
        update_job(job_id, status="failed", progress=100, message=str(exc))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        with active_jobs_lock:
            active_jobs -= 1


def parse_packages_file(path, q, wanted_arch, limit=20):
    opener = open
    mode = "rt"
    if path.endswith(".xz"):
        opener = lzma.open
    elif path.endswith(".gz"):
        opener = gzip.open
    results = []
    current = {}

    def maybe_add(pkg):
        if not pkg:
            return False
        name = pkg.get("Package", "")
        arch = pkg.get("Architecture", "")
        if arch not in (wanted_arch, "all"):
            return False
        if name.startswith(q) or q in name:
            results.append({
                "name": name,
                "version": pkg.get("Version", ""),
                "architecture": arch,
                "description": pkg.get("Description", ""),
            })
        return len(results) >= limit

    with opener(path, mode, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                if maybe_add(current):
                    return results
                current = {}
                continue
            if line.startswith(" "):
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                current[k] = v.strip()
    maybe_add(current)
    return results[:limit]


@app.get("/health")
def health():
    return jsonify({"status": "ok", "release": RELEASE_NAME})


@app.get("/search")
def search():
    arch = request.args.get("arch", "").strip()
    q = request.args.get("q", "").strip().lower()
    if arch not in ALLOWED_ARCHES:
        abort(400, "Invalid architecture")
    if len(q) < 2 or not re.match(r"^[a-z0-9+.-]+$", q):
        return jsonify([])
    apt_update_if_needed()
    candidates = []
    seen = set()
    for root, _, files in os.walk("/var/lib/apt/lists"):
        for fn in files:
            if "Packages" in fn and (fn.endswith("Packages") or fn.endswith("Packages.xz") or fn.endswith("Packages.gz")):
                for item in parse_packages_file(os.path.join(root, fn), q, arch, limit=20):
                    if item["name"] not in seen:
                        seen.add(item["name"])
                        candidates.append(item)
                    if len(candidates) >= 20:
                        return jsonify(candidates)
    return jsonify(candidates)


@app.get("/preview")
def preview():
    release = request.args.get("release", RELEASE_NAME).strip()
    arch = request.args.get("arch", "").strip()
    package = request.args.get("package", "").strip()
    validate_package_arch(package, arch)
    try:
        packages = resolve_with_apt(package, arch)
        _, zip_path, meta_path = cache_paths(release, arch, package, packages)
        total = sum(p["size"] for p in packages)
        return jsonify({
            "package": package,
            "release": release,
            "architecture": arch,
            "package_count": len(packages),
            "download_size_bytes": total,
            "download_size_human": human_size(total),
            "cached": cache_valid(meta_path, zip_path),
            "packages": packages,
        })
    except Exception as exc:
        abort(500, str(exc))


@app.post("/jobs")
def create_job():
    data = request.get_json(force=True)
    release = str(data.get("release", RELEASE_NAME)).strip()
    arch = str(data.get("architecture", "")).strip()
    package = str(data.get("package", "")).strip()
    validate_package_arch(package, arch)
    job_id = uuid.uuid4().hex
    update_job(job_id, status="queued", progress=0, message="Queued", release=release, architecture=arch, package=package)
    t = threading.Thread(target=build_zip_job, args=(job_id, release, arch, package), daemon=True)
    t.start()
    return jsonify({"job_id": job_id, "status": "queued"}), 202


@app.get("/jobs/<job_id>")
def job_status(job_id):
    if not JOB_RE.match(job_id):
        abort(400, "Invalid job id")
    raw = redis_conn.get(f"debzip:job:{job_id}")
    if not raw:
        abort(404, "Job not found")
    return jsonify(json.loads(raw))


@app.get("/jobs/<job_id>/download")
def job_download(job_id):
    if not JOB_RE.match(job_id):
        abort(400, "Invalid job id")
    raw = redis_conn.get(f"debzip:job:{job_id}")
    if not raw:
        abort(404, "Job not found")
    data = json.loads(raw)
    if data.get("status") != "finished":
        abort(409, "Job is not finished")
    zip_path = data.get("zip_path")
    if not zip_path or not os.path.exists(zip_path):
        abort(404, "ZIP not found")
    return send_file(zip_path, as_attachment=True, download_name=os.path.basename(zip_path), mimetype="application/zip")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9000, threaded=True)
