# Architecture

DebZip uses a gateway plus isolated Debian release workers.

```text
Browser
  |
  v
Nginx / TLS
  |
  v
Gateway API
  |
  +--> Redis: rate limits, queue metadata, job status
  |
  +--> worker-oldoldstable: debian:oldoldstable
  +--> worker-oldstable:    debian:oldstable
  +--> worker-stable:       debian:stable
  +--> worker-testing:      debian:testing
  +--> worker-sid:          debian:sid
```

## Gateway

The gateway validates user input, applies per-IP rate limits, serves the frontend, and forwards API calls to the correct release worker.

## Workers

Each worker runs inside a Debian Docker image matching one release track. Workers use APT metadata to resolve packages for the requested architecture and build a ZIP bundle.

## Cache

Generated ZIP files are cached below:

```text
cache/{release}/{architecture}/{package}/{resolver_hash}/
```

A resolver hash includes the selected package and dependency package list. If Debian changes package versions, a new hash is generated.
