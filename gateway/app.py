from flask import Flask, request, jsonify, Response, abort, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import re
import requests

app = Flask(__name__, static_folder="/app/static")

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri=REDIS_URL,
    default_limits=["300 per hour"],
)

PACKAGE_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")
JOB_RE = re.compile(r"^[a-f0-9-]{8,64}$")

ALLOWED_RELEASES = {"oldoldstable", "oldstable", "stable", "testing", "sid"}
ALLOWED_ARCHES = {"amd64", "i386", "arm64", "armhf", "armel", "ppc64el", "s390x", "riscv64"}

WORKERS = {
    "oldoldstable": os.environ.get("WORKER_OLDOLDSTABLE"),
    "oldstable": os.environ.get("WORKER_OLDSTABLE"),
    "stable": os.environ.get("WORKER_STABLE"),
    "testing": os.environ.get("WORKER_TESTING"),
    "sid": os.environ.get("WORKER_SID"),
}


def validate_release_arch_package(package_required=True):
    release = request.args.get("release", "").strip()
    arch = request.args.get("arch", "").strip()
    package = request.args.get("package", "").strip()

    if release not in ALLOWED_RELEASES:
        abort(400, "Invalid release")
    if arch not in ALLOWED_ARCHES:
        abort(400, "Invalid architecture")
    if package_required and not PACKAGE_RE.match(package):
        abort(400, "Invalid package name")
    if not WORKERS.get(release):
        abort(500, "Worker not configured")

    return release, arch, package


def proxy_json(method, url, **kwargs):
    try:
        upstream = requests.request(method, url, timeout=kwargs.pop("timeout", 120), **kwargs)
    except requests.RequestException as exc:
        abort(502, f"Worker unavailable: {exc}")
    return Response(
        upstream.content,
        status=upstream.status_code,
        content_type=upstream.headers.get("Content-Type", "application/json"),
    )


@app.get("/")
def index():
    return send_from_directory("/app/static", "index.html")


@app.get("/api/releases")
def releases():
    return jsonify({
        "releases": sorted(ALLOWED_RELEASES),
        "architectures": sorted(ALLOWED_ARCHES),
    })


@app.get("/api/search")
@limiter.limit("60 per minute")
def search():
    release = request.args.get("release", "").strip()
    arch = request.args.get("arch", "").strip()
    q = request.args.get("q", "").strip().lower()

    if release not in ALLOWED_RELEASES:
        abort(400, "Invalid release")
    if arch not in ALLOWED_ARCHES:
        abort(400, "Invalid architecture")
    if len(q) < 2:
        return jsonify([])
    if not re.match(r"^[a-z0-9+.-]+$", q):
        abort(400, "Invalid search query")

    return proxy_json("GET", f"{WORKERS[release]}/search", params={"arch": arch, "q": q}, timeout=30)


@app.get("/api/preview")
@limiter.limit("30 per minute")
def preview():
    release, arch, package = validate_release_arch_package()
    return proxy_json(
        "GET",
        f"{WORKERS[release]}/preview",
        params={"release": release, "arch": arch, "package": package},
        timeout=180,
    )


@app.post("/api/jobs")
@limiter.limit("20 per hour")
def create_job():
    data = request.get_json(force=True, silent=False)
    release = str(data.get("release", "")).strip()
    arch = str(data.get("architecture", "")).strip()
    package = str(data.get("package", "")).strip()

    if release not in ALLOWED_RELEASES:
        abort(400, "Invalid release")
    if arch not in ALLOWED_ARCHES:
        abort(400, "Invalid architecture")
    if not PACKAGE_RE.match(package):
        abort(400, "Invalid package name")

    return proxy_json(
        "POST",
        f"{WORKERS[release]}/jobs",
        json={"release": release, "architecture": arch, "package": package},
        timeout=30,
    )


@app.get("/api/jobs/<job_id>")
@limiter.limit("180 per minute")
def job_status(job_id):
    release = request.args.get("release", "").strip()
    if release not in ALLOWED_RELEASES:
        abort(400, "Invalid release")
    if not JOB_RE.match(job_id):
        abort(400, "Invalid job id")
    return proxy_json("GET", f"{WORKERS[release]}/jobs/{job_id}", timeout=30)


@app.get("/api/jobs/<job_id>/download")
@limiter.limit("30 per hour")
def job_download(job_id):
    release = request.args.get("release", "").strip()
    if release not in ALLOWED_RELEASES:
        abort(400, "Invalid release")
    if not JOB_RE.match(job_id):
        abort(400, "Invalid job id")

    try:
        upstream = requests.get(f"{WORKERS[release]}/jobs/{job_id}/download", stream=True, timeout=900)
    except requests.RequestException as exc:
        abort(502, f"Worker unavailable: {exc}")

    headers = {}
    for h in ["Content-Type", "Content-Disposition", "Content-Length"]:
        if h in upstream.headers:
            headers[h] = upstream.headers[h]

    return Response(upstream.iter_content(chunk_size=1024 * 1024), status=upstream.status_code, headers=headers)


@app.get("/api/public-key")
def public_key():
    key_path = "/keys/debzip-public-key.asc"
    if not os.path.exists(key_path):
        abort(404, "Public key not available")
    with open(key_path, "r", encoding="utf-8") as f:
        return Response(f.read(), content_type="text/plain; charset=utf-8")
