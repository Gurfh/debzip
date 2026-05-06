# Limitations

- Dependency resolution uses APT `--print-uris`. This is practical and close to real APT behavior, but package relationships can still be complex for virtual packages, alternatives, and multi-arch scenarios.
- The initial implementation starts background jobs in worker API containers with Python threads. For heavy production use, replace this with separate RQ/Celery worker containers.
- `testing` and `sid` change frequently. Their cache TTL is intentionally short.
- The service downloads packages from Debian mirrors at job execution time. If a mirror changes while a job is running, retrying may be required.
- This tool creates a transfer bundle. It does not guarantee that installing the bundle with `dpkg -i` will satisfy all local target-system constraints.
