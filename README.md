# DebZip — Debian Dependency ZIP Downloader

DebZip is a Docker-based web service that lets a user select a Debian release, architecture, and package, then creates a ZIP file containing the requested `.deb` package plus its dependency packages.

It is intended for offline, air-gapped, legacy, or industrial Debian environments where transferring a dependency bundle is easier than running `apt` directly on the target system.

## Features

- Debian release selector: `oldoldstable`, `oldstable`, `stable`, `testing`, `sid`
- Architecture selector: `amd64`, `i386`, `arm64`, `armhf`, `armel`, `ppc64el`, `s390x`, `riscv64`
- Package search/autocomplete
- ZIP size preview before starting a job
- Background job handling for large dependency trees
- Redis-backed job state
- Per-IP rate limiting in the gateway
- Cache with release-dependent expiry
- Signed manifest with package filenames, versions, sizes, SHA256 hashes, and source URLs
- Docker worker isolation per Debian release

## Quick start

```bash
cp .env.example .env
mkdir -p cache keys
./scripts/generate-gpg-key.sh

docker compose up -d --build
```

Open:

```text
http://localhost:8000
```

## Basic workflow

1. Select Debian release.
2. Select architecture.
3. Search for a package.
4. Preview dependencies and total download size.
5. Create a background job.
6. Download the generated ZIP when complete.

## Production deployment

See [`docs/deployment-ionos.md`](docs/deployment-ionos.md).

## License

MIT. See [`LICENSE`](LICENSE).
