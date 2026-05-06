# API

## `GET /api/releases`

Returns supported releases and architectures.

## `GET /api/search`

Query parameters:

- `release`
- `arch`
- `q`

Example:

```bash
curl 'http://localhost:8000/api/search?release=stable&arch=amd64&q=curl'
```

## `GET /api/preview`

Query parameters:

- `release`
- `arch`
- `package`

Returns dependency count, estimated download size, cache status, and package file list.

## `POST /api/jobs`

Body:

```json
{
  "release": "stable",
  "architecture": "amd64",
  "package": "curl"
}
```

Returns:

```json
{
  "job_id": "...",
  "status": "queued"
}
```

## `GET /api/jobs/{job_id}`

Returns progress and status.

## `GET /api/jobs/{job_id}/download`

Downloads the generated ZIP after the job is finished.

## `GET /api/public-key`

Returns the public GPG key used to verify `MANIFEST.txt.asc`.
