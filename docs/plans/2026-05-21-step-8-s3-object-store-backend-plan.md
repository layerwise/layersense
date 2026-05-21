# S3-Compatible ObjectStore Backend — Implementation Plan

**Status:** Proposed (not yet scheduled)
**Step in build order:** 8 of 9
**Depends on:** Step 3 (`layersense_storage` + `LocalFSObjectStore`) merged and stable; Steps 4–7 merged (the key layout and artifact-serving routes must be in their final post-Step-4 shape before this lands)
**Unblocks:** Step 9 (OpenCode-style agentic runtime, speculative); hosted deployment; multi-machine rendering

---

## Why this step

**Do not run this step until at least one of the following is true:**

1. **Multi-machine rendering** — the Taskiq worker runs on a different host than the controller API, and a shared filesystem is no longer viable.
2. **Hosted deployment** — the system is deployed to a cloud environment where local-disk persistence is ephemeral or insufficient.
3. **Distributed workers** — multiple worker replicas are needed and they cannot share a single NFS/EFS mount without unacceptable latency or operational complexity.
4. **Storage volume pressure** — the local artifact tree has grown large enough that a managed object store's lifecycle policies, tiering, or cost profile are worth the operational overhead.

For a single-developer local workflow, `LocalFSObjectStore` is indefinitely sufficient. The protocol was designed to admit an S3 backend without caller changes; this step makes that backend real. The default stays `local` and is never changed automatically.

---

## Scope

### In scope

1. `S3ObjectStore` class implementing the `ObjectStore` protocol from `layersense_storage`, configured via environment variables, working against any S3-compatible endpoint.
2. `prefers_redirect` method added to the `ObjectStore` protocol; `LocalFSObjectStore` returns `False`, `S3ObjectStore` returns `True`.
3. Controller artifact-serving routes (`/artifacts/by-hash/...`, `/artifacts/scenes/...`) branch on `prefers_redirect`: S3 path returns `RedirectResponse` to a presigned URL; local path keeps the existing streaming `FileResponse`.
4. Config switch `LAYERSENSE_OBJECT_STORE_BACKEND=local|s3` defaulting to `local`. No behavior change unless explicitly set to `s3`.
5. New S3-related config fields: `LAYERSENSE_S3_ENDPOINT_URL`, `LAYERSENSE_S3_ACCESS_KEY`, `LAYERSENSE_S3_SECRET_KEY`, `LAYERSENSE_S3_BUCKET`, `LAYERSENSE_S3_PRESIGNED_URL_TTL_SECONDS`.
6. Compose service for RustFS (design-time reference backend) as an opt-in dev/test target.
7. Migration utility: `layersense-storage migrate-local-to-s3 --confirm` — one-shot, idempotent, local → S3 only.
8. `moto`-backed unit and integration tests for `S3ObjectStore`, including protocol-conformance parameterization.
9. Opt-in e2e recipe `just test-e2e-s3` running the full stack with RustFS in compose.

### Out of scope

- Making S3 the default backend. The default is `local`, permanently unless Mathias explicitly changes it.
- Choosing the specific S3-compatible backend for production. That decision is deferred to adoption time (see "Backend choice" section below).
- Multi-region replication, cross-region failover.
- S3 lifecycle policies, intelligent tiering, storage class transitions.
- IAM roles, instance profiles, STS assume-role, or any auth model beyond a single static access-key/secret-key pair scoped to one bucket.
- S3 → local reverse migration (hand-roll when needed; not worth engineering now).
- CDN integration or signed-URL caching layers.
- Multipart upload resumability / upload-ID persistence across process restarts.

---

## Design

### `S3ObjectStore` implementation

#### Client construction

```python
import boto3
from botocore.config import Config

class S3ObjectStore:
    def __init__(self, settings: S3StorageSettings) -> None:
        self._bucket = settings.s3_bucket
        self._ttl = settings.s3_presigned_url_ttl_seconds
        self._client = boto3.client(
            "s3",
            endpoint_url=str(settings.s3_endpoint_url),
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            config=Config(signature_version="s3v4"),
        )
```

`SecretStr` from Pydantic is used for `s3_access_key` and `s3_secret_key` so they are never accidentally logged or serialized. The `endpoint_url` field accepts any S3-compatible base URL (e.g., `http://localhost:9000` for RustFS in compose, `https://s3.amazonaws.com` for AWS, `https://<account>.r2.cloudflarestorage.com` for R2).

`signature_version="s3v4"` is required by most S3-compatible backends (RustFS, Garage, SeaweedFS, R2). Do not omit it.

#### Error mapping

All `botocore.exceptions.ClientError` with `Error.Code == "NoSuchKey"` (or `"404"` from some backends) are caught and re-raised as `ObjectNotFoundError` from `layersense_storage.errors`. All other `ClientError` instances are re-raised as `ObjectStoreError`. This keeps callers backend-agnostic.

```python
def _raise_if_not_found(self, exc: ClientError, key: str) -> None:
    code = exc.response["Error"]["Code"]
    if code in ("NoSuchKey", "404", "NoSuchBucket"):
        raise ObjectNotFoundError(key) from exc
    raise ObjectStoreError(str(exc)) from exc
```

#### `put` and `put_stream`

- `put(key, data)`: `client.put_object(Bucket=..., Key=key, Body=data, ContentType=content_type or "application/octet-stream")`. For data ≤ 50 MB, single-part upload.
- `put_stream(key, source)`: uses `boto3`'s `upload_fileobj` with a `TransferConfig` that sets `multipart_threshold=50 * 1024 * 1024` (50 MB) and `multipart_chunksize=5 * 1024 * 1024` (5 MB). `upload_fileobj` handles the multipart/single-part decision internally. This is the correct path for large mp4 finals.

Most rendered mp4s are < 50 MB. Multipart only activates for long-form videos. The thresholds are module-level constants (not settings), matching the Step 1 precedent for operational knobs that don't need per-deployment tuning.

#### `get` and `open`

- `get(key)`: `client.get_object(...)["Body"].read()`. Raises `ObjectNotFoundError` on `NoSuchKey`.
- `open(key)`: returns `client.get_object(...)["Body"]` — the streaming `StreamingBody` object, which is `BinaryIO`-compatible for chunked reads. Callers that use `open` for FastAPI streaming responses will not use this path when `prefers_redirect` is `True` (they'll redirect instead), but the method must still be implemented for protocol conformance and for non-HTTP callers (e.g., the migration utility).

#### `head`

```python
def head(self, key: str) -> ObjectInfo | None:
    try:
        resp = self._client.head_object(Bucket=self._bucket, Key=key)
        return ObjectInfo(
            size=resp["ContentLength"],
            content_type=resp.get("ContentType", "application/octet-stream"),
            etag=resp["ETag"].strip('"'),
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return None
        raise ObjectStoreError(str(exc)) from exc
```

#### `delete` and `list_prefix`

- `delete(key)`: `client.delete_object(...)`. S3 delete is idempotent (no error if key absent); wrap in a try/except for non-S3 backends that may differ.
- `list_prefix(prefix)`: paginate via `client.get_paginator("list_objects_v2").paginate(Bucket=..., Prefix=prefix)`, yield `obj["Key"]` for each page. Handles buckets with > 1000 objects correctly.

#### `url_for` and `prefers_redirect`

```python
def url_for(self, key: str) -> str:
    return self._client.generate_presigned_url(
        "get_object",
        Params={"Bucket": self._bucket, "Key": key},
        ExpiresIn=self._ttl,
    )

def prefers_redirect(self) -> bool:
    return True
```

`LocalFSObjectStore.url_for` continues to return the absolute filesystem path string (unchanged from Step 3). `LocalFSObjectStore.prefers_redirect` returns `False`.

**Protocol addition:** `prefers_redirect` is added to the `ObjectStore` Protocol with a default implementation returning `False`. This is a non-breaking addition — existing `LocalFSObjectStore` gets the method added explicitly; any future impl that doesn't override it defaults to `False` (safe).

---

### Etag semantics

`LocalFSObjectStore` computes `ObjectInfo.etag` as `sha256(contents).hexdigest()` — a deterministic, content-addressed hex string.

S3 returns an ETag that is:
- MD5 of the object for single-part uploads.
- `md5(part1) + md5(part2) + ...-N` for multipart uploads (where N is the part count).

These are **not comparable across backends**. A caller that stores an etag from the local impl and later checks it against the S3 impl will get a false mismatch.

**Resolution:** `ObjectInfo.etag` is documented as **opaque and backend-specific**. Callers must not compare etags across backends. The only valid use of `etag` is:
1. Cache-validation within the same backend (e.g., "has this key changed since I last read it?").
2. Integrity verification of a single `get` against a previously stored `head` from the same backend.

The migration utility (local → S3) uses `head` on the S3 side to check for presence by **size**, not etag, to avoid cross-backend etag comparison. This is documented in the migration utility's docstring.

Add a comment to `ObjectInfo` in `object_store.py`:

```python
@dataclass
class ObjectInfo:
    size: int
    content_type: str
    etag: str
    """
    Opaque, backend-specific. SHA-256 hex for LocalFSObjectStore;
    MD5 (or multipart composite) for S3ObjectStore.
    Do NOT compare etags across backends.
    """
```

---

### Route changes: `RedirectResponse` for presigned URLs

The controller's artifact-serving routes currently call `ObjectStore.open(key)` and return a `FileResponse` or a streaming response. After this step they branch:

```python
# layersense_controller/src/layersense_controller/router.py (sketch)

async def serve_artifact(key: str, object_store: ObjectStore) -> Response:
    if object_store.prefers_redirect():
        url = object_store.url_for(key)   # presigned URL
        return RedirectResponse(url=url, status_code=302)
    else:
        info = object_store.head(key)
        if info is None:
            raise HTTPException(status_code=404)
        return StreamingResponse(
            object_store.open(key),
            media_type=info.content_type,
            headers={"Content-Length": str(info.size)},
        )
```

This helper is extracted and shared by all artifact routes (`/artifacts/by-hash/{hash}/preview`, `/artifacts/by-hash/{hash}/final`, `/artifacts/scenes/{scene_uuid}`, etc.) to avoid duplicating the branch.

**`302` vs `307`:** Use `302 Found`. The browser will follow it with a `GET` regardless of the original method. `307` is semantically more correct for method-preserving redirects but all artifact routes are `GET`-only, so `302` is fine and more widely understood.

**CORS complication (see "Key design questions" below):** when the browser fetches an mp4 from a presigned S3 URL, the origin of that URL differs from the controller's origin. The bucket must have a CORS policy permitting `GET` from the frontend's origin. Document the required policy in `docs/ops/s3-bucket-setup.md` (new file, created in this step). For local dev with RustFS in compose, the presigned URL will contain `http://rustfs:9000/...` — a hostname the browser cannot resolve. See the "Local dev CORS / hostname rewrite" subsection below.

---

### Local dev CORS / hostname rewrite

When running the full stack in compose with RustFS, the controller generates presigned URLs using the internal compose hostname (`http://rustfs:9000`). The browser cannot reach this hostname.

**Options:**

1. **Controller proxies the artifact** (ignore `prefers_redirect` in local-dev S3 mode): add a `LAYERSENSE_S3_PUBLIC_ENDPOINT_URL` setting. If set, the controller rewrites the presigned URL's host to this public endpoint before redirecting. In compose, set `LAYERSENSE_S3_PUBLIC_ENDPOINT_URL=http://localhost:9000` and expose RustFS port 9000 to the host. The presigned URL is generated against the internal endpoint (for auth), then the host portion is rewritten to the public endpoint before the `RedirectResponse` is issued.

2. **Controller proxies the bytes** (never redirect in local-dev S3 mode): add a `LAYERSENSE_S3_FORCE_PROXY=true` env var that makes `prefers_redirect()` return `False` even for S3, causing the controller to stream bytes from S3 to the browser. Simpler for local dev; loses the redirect optimization.

**Recommendation:** Option 1 (host rewrite via `LAYERSENSE_S3_PUBLIC_ENDPOINT_URL`). It preserves the redirect path in production while making local dev work without a proxy. The rewrite is a simple `urllib.parse.urlparse` + `_replace(netloc=public_netloc)` on the presigned URL string. Document that the presigned URL's signature covers the path and query, not the host, so the rewrite does not invalidate the signature for most S3-compatible backends (verify this for RustFS specifically before shipping).

**CORS bucket policy** (for hosted deployment, not local dev):

```json
[
  {
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET"],
    "AllowedOrigins": ["https://your-frontend-origin.example.com"],
    "ExposeHeaders": ["Content-Length", "Content-Type", "ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

For local dev with the host-rewrite approach, CORS is not needed because the browser fetches from `http://localhost:9000` (same-origin as the compose-exposed port, or at least not cross-origin in the way that triggers CORS preflight for video playback).

---

### Compose service for RustFS

RustFS is the design-time reference backend (per overview decision #5). The compose service is opt-in — it is defined in a separate overlay file `docker-compose.s3.yml`, not in the default `docker-compose.yml`. Running the stack with S3 requires:

```bash
docker compose -f docker-compose.yml -f docker-compose.s3.yml up --build
```

**`docker-compose.s3.yml` sketch:**

```yaml
services:
  rustfs:
    image: rustfs/rustfs:latest   # pin to a specific digest before shipping
    ports:
      - "9000:9000"
      - "9001:9001"   # RustFS console
    environment:
      RUSTFS_ROOT_USER: layersense
      RUSTFS_ROOT_PASSWORD: layersense-dev-secret   # dev-only; never in production
      RUSTFS_VOLUMES: /data
    volumes:
      - rustfs_data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 5s
      timeout: 3s
      retries: 10

  controller:
    environment:
      LAYERSENSE_OBJECT_STORE_BACKEND: s3
      LAYERSENSE_S3_ENDPOINT_URL: http://rustfs:9000
      LAYERSENSE_S3_ACCESS_KEY: layersense
      LAYERSENSE_S3_SECRET_KEY: layersense-dev-secret
      LAYERSENSE_S3_BUCKET: layersense-artifacts
      LAYERSENSE_S3_PUBLIC_ENDPOINT_URL: http://localhost:9000

  controller-worker:
    environment:
      LAYERSENSE_OBJECT_STORE_BACKEND: s3
      LAYERSENSE_S3_ENDPOINT_URL: http://rustfs:9000
      LAYERSENSE_S3_ACCESS_KEY: layersense
      LAYERSENSE_S3_SECRET_KEY: layersense-dev-secret
      LAYERSENSE_S3_BUCKET: layersense-artifacts

volumes:
  rustfs_data:
```

**Bucket creation:** RustFS (like MinIO) does not auto-create buckets. Add a one-shot `rustfs-init` service that runs `mc mb rustfs/layersense-artifacts` and exits, with `depends_on: rustfs: condition: service_healthy`. Alternatively, add bucket auto-creation to the controller's startup sequence (check `head_bucket`, create if absent). The latter is simpler and avoids an extra compose service.

**Backend choice note:** The compose overlay uses RustFS as the reference. Swapping to Garage, SeaweedFS, or any other S3-compatible backend requires only changing the `image:` line and any backend-specific env vars. The controller code is backend-agnostic.

---

### Backend choice discussion

The overview chose RustFS as the design-time reference. The final backend choice is deferred to adoption time. Candidates:

| Backend | Pros | Cons |
|---|---|---|
| **RustFS** | Rust-native, S3-compatible, single binary, active development, MIT-licensed | Newer project, less battle-tested than MinIO; API surface still evolving |
| **Garage** | Distributed by design, geo-aware, AGPL, very lightweight | Distributed-first (overkill for single-node); less S3 API coverage |
| **SeaweedFS** | Mature, high throughput, S3 gateway mode | More complex ops; Go-based; less S3-native |
| **Cloudflare R2** | Zero egress fees, global, managed | Vendor lock-in; requires internet; no local dev equivalent |
| **Backblaze B2** | Cheap, S3-compatible, reliable | Egress fees; no local dev equivalent |
| **AWS S3** | The reference implementation; maximum SDK compatibility | Cost at scale; vendor lock-in; no local dev equivalent |

**Recommendation:** choose at adoption time based on deployment context. For a self-hosted single-machine deployment, RustFS or SeaweedFS. For a cloud deployment, R2 or S3. The `S3ObjectStore` implementation is backend-agnostic; the only backend-specific concern is the CORS policy and the presigned URL host-rewrite for local dev.

**MinIO is excluded** per overview decision #5 (repo archive / commercialization move). Do not add MinIO to compose or documentation.

---

### Config

New settings in `layersense_storage/src/layersense_storage/config.py`:

```python
class StorageSettings(BaseSettings):
    # existing
    storage_root: Path = Path("./layersense_artifacts/storage")

    # new in Step 8
    object_store_backend: Literal["local", "s3"] = "local"

    # S3 settings — only required when object_store_backend == "s3"
    s3_endpoint_url: AnyHttpUrl | None = None
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    s3_bucket: str | None = None
    s3_presigned_url_ttl_seconds: int = 3600          # 1 hour default
    s3_public_endpoint_url: AnyHttpUrl | None = None  # host rewrite for local dev

    model_config = SettingsConfigDict(env_prefix="LAYERSENSE_")
```

A factory function `make_object_store(settings: StorageSettings) -> ObjectStore` is added to `layersense_storage` and used by the controller's dependency injection. It validates that all required S3 fields are present when `object_store_backend == "s3"` and raises a clear `ValueError` at startup if any are missing.

**`.env` documentation:** add a commented block to `.env.example` (or equivalent) documenting all six new env vars. Never put real credentials in any committed file.

---

### Migration utility

A CLI entry point added to `layersense_storage`:

```
uv run --package layersense-storage layersense-storage migrate-local-to-s3 --confirm
```

**Behavior:**

1. Reads `StorageSettings` from the environment (both local and S3 settings must be present).
2. Instantiates both `LocalFSObjectStore` and `S3ObjectStore`.
3. Walks `LocalFSObjectStore.list_prefix("")` (all keys).
4. For each key:
   a. Calls `S3ObjectStore.head(key)`.
   b. If present and `size == local_info.size`: skip (idempotent).
   c. Otherwise: `S3ObjectStore.put_stream(key, local_store.open(key), content_type=local_info.content_type)`.
5. Prints a summary: `N keys copied, M skipped (already present), K failed`.
6. Exits non-zero if any key failed.

**`--confirm` flag is required.** Without it, the utility prints a dry-run summary and exits. This prevents accidental runs.

**Idempotency:** size-based skip (not etag, to avoid cross-backend etag comparison). If a key is present on S3 with the same size, it is assumed correct. If sizes differ, it is re-uploaded (overwrite).

**No reverse migration** (S3 → local) in this step. If needed, hand-roll with `aws s3 sync` or equivalent.

**Entry point registration** in `layersense_storage/pyproject.toml`:

```toml
[project.scripts]
layersense-storage = "layersense_storage.cli:main"
```

The CLI module is minimal: `argparse` or `click`, one subcommand `migrate-local-to-s3`.

---

## File-level changes

### `layersense_storage`

| File | Change |
|---|---|
| `src/layersense_storage/object_store.py` | Add `prefers_redirect()` to `ObjectStore` Protocol (default `False`); add `S3ObjectStore` class; update `LocalFSObjectStore` with explicit `prefers_redirect` returning `False` |
| `src/layersense_storage/config.py` | Add S3 settings fields; add `make_object_store` factory |
| `src/layersense_storage/errors.py` | No change (existing `ObjectNotFoundError`, `ObjectStoreError` are sufficient) |
| `src/layersense_storage/cli.py` | New — migration utility entry point |
| `src/layersense_storage/__init__.py` | Export `S3ObjectStore`, `make_object_store` |
| `pyproject.toml` | Add `boto3` dependency; add `[project.scripts]` entry; add `moto[s3]` to `[dependency-groups.test]` |
| `tests/unit/test_s3_object_store.py` | New — moto-backed unit tests |
| `tests/integration/test_object_store_protocol_conformance.py` | New — parameterized protocol-conformance suite running against both `LocalFSObjectStore` and `S3ObjectStore + moto` |
| `tests/unit/test_migration_cli.py` | New — migration utility unit tests |

### `layersense_controller`

| File | Change |
|---|---|
| `src/layersense_controller/router.py` | Extract `serve_artifact` helper; branch on `prefers_redirect()`; return `RedirectResponse` for S3, `StreamingResponse` for local |
| `src/layersense_controller/dependencies.py` (or equivalent DI module) | Use `make_object_store(settings)` instead of directly instantiating `LocalFSObjectStore` |
| `src/layersense_controller/config.py` | Import `StorageSettings` from `layersense_storage`; no new fields needed here (all S3 config lives in `layersense_storage`) |
| `tests/integration/test_router_api.py` | Add test: `/artifacts/by-hash/...` returns `302` when backend is S3 (moto fixture) |

### Compose

| File | Change |
|---|---|
| `docker-compose.s3.yml` | New — opt-in overlay with RustFS service + controller/worker S3 env overrides |
| `docker-compose.e2e.s3.yml` | New — e2e variant overlay for `just test-e2e-s3` |
| `docker-compose.yml` | No change (default stays local) |

### `justfile`

| Recipe | Change |
|---|---|
| `test-e2e-s3` | New — `docker compose -f docker-compose.yml -f docker-compose.e2e.yml -f docker-compose.e2e.s3.yml up --build --abort-on-container-exit` |

### Docs

| File | Change |
|---|---|
| `docs/ops/s3-bucket-setup.md` | New — CORS policy, bucket creation, env var reference |
| `docs/plans/2026-05-21-architecture-expansion-overview.md` | Update Step 8 entry to "Implemented" once shipped |
| `README.md` | Add a brief "S3 backend (opt-in)" section under "Local Docker Dev Stack" |

---

## Test plan

### Unit tests (`layersense_storage`)

All backed by `moto` (`@mock_aws` decorator). No real S3 endpoint required.

- `put` + `get` roundtrip: bytes in == bytes out.
- `head` returns correct `size` and `etag`; `etag` is the S3 ETag (MD5), not SHA-256.
- `head` on missing key returns `None`.
- `get` on missing key raises `ObjectNotFoundError`.
- `put_stream` with a 60 MB `BytesIO` triggers multipart upload (verify via `moto`'s recorded calls); bytes are correct.
- `delete` removes key; subsequent `head` returns `None`; `get` raises `ObjectNotFoundError`.
- `list_prefix` returns all keys under prefix; handles pagination (> 1000 objects via moto).
- `url_for` returns a string containing the bucket name and key; does not raise.
- `prefers_redirect` returns `True`.
- `ClientError` with non-404 code raises `ObjectStoreError`, not `ObjectNotFoundError`.
- `make_object_store(settings)` with `backend="local"` returns `LocalFSObjectStore`.
- `make_object_store(settings)` with `backend="s3"` and all fields set returns `S3ObjectStore`.
- `make_object_store(settings)` with `backend="s3"` and missing `s3_bucket` raises `ValueError` at construction time.

### Integration tests — protocol conformance (`layersense_storage`)

A single parameterized test module `test_object_store_protocol_conformance.py` runs the same test cases against both backends:

```python
@pytest.fixture(params=["local", "s3"])
def object_store(request, tmp_path, aws_credentials):
    if request.param == "local":
        yield LocalFSObjectStore(root=tmp_path)
    else:
        with mock_aws():
            client = boto3.client("s3", region_name="us-east-1")
            client.create_bucket(Bucket="test-bucket")
            yield S3ObjectStore(S3StorageSettings(bucket="test-bucket", ...))
```

Protocol-conformance cases (same assertions for both backends):
- `put` / `get` roundtrip.
- `head` on present key: `size` matches `len(data)`.
- `head` on absent key: `None`.
- `get` on absent key: `ObjectNotFoundError`.
- `delete` then `head`: `None`.
- `list_prefix` returns only keys under the given prefix.
- `put_stream` produces bytes identical to `put` for the same content.
- `open` returns a readable stream; reading it yields the original bytes.

This suite is the contract guarantee: if both backends pass, callers can switch backends without behavioral surprises (modulo etag semantics, which are explicitly documented as opaque).

### Integration tests — controller routes (`layersense_controller`)

- `GET /artifacts/by-hash/{hash}/preview` with `LocalFSObjectStore`: returns `200` with `Content-Type: video/mp4` and correct bytes (existing test, unchanged).
- `GET /artifacts/by-hash/{hash}/preview` with `S3ObjectStore + moto`: returns `302` with `Location` header containing the bucket name and key. Verify the redirect URL is a valid presigned URL string.
- `GET /artifacts/by-hash/{hash}/preview` with S3 backend and missing key: returns `404` (the controller must check `head` before redirecting, or handle the presigned URL generation for a missing key gracefully — see risk table).
- `GET /artifacts/scenes/{scene_uuid}` with S3 backend: returns `302`.

### e2e (opt-in)

`just test-e2e-s3` runs the full compose stack with RustFS. The e2e test suite (`tests/e2e/test_dev_stack_e2e.py`) is reused without modification — the behavior from the browser's perspective is identical (it follows the redirect). The test runner must follow redirects (verify `httpx` / `requests` client is configured to do so, or assert on the `302` + `Location` header explicitly).

This recipe is **not** part of the default `just test-e2e`. It is opt-in, documented in the justfile with a comment explaining the RustFS dependency.

---

## Acceptance criteria

1. `LAYERSENSE_OBJECT_STORE_BACKEND=local` (default): behavior is **byte-identical** to pre-Step-8. Verified by running `just test-e2e` (no S3 overlay) and confirming all existing tests pass without modification.
2. `grep -rn "S3ObjectStore\|boto3\|aioboto3" layersense_controller/src` returns no matches — S3 client code lives only in `layersense_storage`.
3. `grep -rn "LocalFSObjectStore" layersense_controller/src` returns no matches — the controller uses `make_object_store` and the `ObjectStore` protocol only.
4. `uv run --all-packages pytest -m unit` passes.
5. `uv run --all-packages pytest -m integration` passes (moto-backed; no real S3 endpoint required).
6. `just lint` passes.
7. `just test-e2e` passes (local backend, no RustFS).
8. `just test-e2e-s3` passes (opt-in; requires Docker and RustFS image pull).
9. `docker-compose.yml` is unchanged — no RustFS service, no S3 env vars in the default compose file.
10. `layersense-storage migrate-local-to-s3 --confirm` runs to completion against a local + moto S3 pair in a test; `--confirm` omitted prints dry-run output and exits 0 without writing anything.
11. `docs/ops/s3-bucket-setup.md` exists and documents the CORS policy and required env vars.
12. Coverage for `layersense_storage/src/**` does not regress from Step 3's ≥ 95% baseline.
13. `S3ObjectStore` unit + integration coverage ≥ 90%.
14. No real AWS credentials are required to run `just test` or `just test_python`. All S3 tests use moto.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| **Presigned URL TTL too short** — browser starts playback, URL expires mid-stream | Default TTL is 1 hour. For a single-user local workflow, renders are fetched immediately after completion; 1 hour is ample. For hosted deployment, increase TTL or implement URL refresh. Document the tradeoff in `docs/ops/s3-bucket-setup.md`. |
| **CORS misconfiguration** — browser blocks mp4 fetch from presigned URL origin | Document the required bucket CORS policy in `docs/ops/s3-bucket-setup.md`. For local dev, use the `LAYERSENSE_S3_PUBLIC_ENDPOINT_URL` host-rewrite to avoid cross-origin issues. |
| **Presigned URL for missing key** — `generate_presigned_url` succeeds even if the key doesn't exist; the browser gets a 403/404 from S3 instead of a clean 404 from the controller | Always call `head(key)` before generating the presigned URL. If `head` returns `None`, return `404` from the controller. This adds one extra S3 API call per artifact serve, but it's cheap and gives clean error semantics. |
| **Backend SDK API drift** — `boto3` API changes or a specific S3-compatible backend deviates from the S3 API | Pin `boto3` to a minor version range in `pyproject.toml`. The protocol-conformance test suite catches behavioral regressions. For backend-specific quirks (e.g., RustFS ETag format), document them in `docs/ops/s3-bucket-setup.md`. |
| **Cost surprises on cloud backends** — presigned URL generation is free, but `GET` requests and egress are billed | Not a concern for local dev (RustFS). For hosted deployment, document the cost model of the chosen backend. R2 has zero egress; S3 does not. |
| **Etag semantics divergence** — code that compares etags across backends will silently produce wrong results | `ObjectInfo.etag` is documented as opaque. The migration utility uses size-based skip, not etag comparison. Add a lint-level comment to `ObjectInfo` and a note in the protocol docstring. |
| **Migration utility data loss** — a bug in the migration utility could overwrite or skip objects | The utility is idempotent (skip if size matches) and requires `--confirm`. Dry-run mode (default without `--confirm`) prints what would be copied. Recommend running dry-run first and inspecting output before `--confirm`. |
| **RustFS image availability** — `rustfs/rustfs:latest` may not be available or may break on a new release | Pin to a specific image digest in `docker-compose.s3.yml`. Document the pinned version and the process for updating it. |
| **Presigned URL host rewrite invalidates signature** — some backends include the host in the signed string | Verify for RustFS specifically. If host is included in the signature, the rewrite approach breaks and Option 2 (proxy bytes) must be used instead. Document the finding in `docs/ops/s3-bucket-setup.md`. |
| **`put_stream` with non-seekable stream** — `boto3`'s `upload_fileobj` requires a seekable stream for multipart retry | Wrap non-seekable streams in a `BytesIO` buffer for objects above the multipart threshold, or disable multipart retry. For the controller's use case (writing Manim output files), the source is always a real file handle (seekable). Document the constraint. |

---

## Estimated shape

| Package | Delta |
|---|---|
| `layersense_storage` src | ~350 LOC (`S3ObjectStore` ~200, `cli.py` ~80, `config.py` additions ~40, `__init__.py` ~30) |
| `layersense_storage` tests | ~500 LOC (unit ~200, protocol conformance ~200, migration CLI ~100) |
| `layersense_controller` src | ~80 LOC (route branching, DI factory swap) |
| `layersense_controller` tests | ~80 LOC (S3 route tests) |
| Compose files | ~60 lines (`docker-compose.s3.yml`, `docker-compose.e2e.s3.yml`) |
| `justfile` | ~5 lines |
| Docs | ~100 lines (`docs/ops/s3-bucket-setup.md`, README addition) |

**Total: ~1175 LOC delta.** Smaller than Step 3 (the substrate change). Most of the work is in `layersense_storage`; the controller changes are mechanical.

---

## Assumptions

Surface these explicitly; push back before implementation begins.

1. **`boto3` (sync) over `aioboto3` (async).** The controller is async (FastAPI), but the artifact-serving routes are not on the hot path for throughput — single user, one render at a time. Wrapping `boto3` calls in `run_in_threadpool` at the FastAPI route boundary is sufficient. `aioboto3` adds a dependency and async complexity for marginal benefit. → *Push back if you expect concurrent artifact fetches to be a bottleneck.*

2. **`moto` is an acceptable test boundary for unit and integration tests.** Real S3-compatible backend testing is reserved for the opt-in `just test-e2e-s3` recipe. `moto` covers the boto3 API surface well enough for protocol-conformance testing. → *Push back if you want a real backend in CI.*

3. **Presigned URL TTL default of 1 hour.** Long enough for typical render preview/playback sessions (renders complete in seconds to minutes; the user watches immediately). Short enough that a leaked URL expires within the hour. → *Push back if you expect long-lived sessions or deferred playback.*

4. **RustFS as the compose reference backend.** The `docker-compose.s3.yml` overlay uses RustFS. Swapping to Garage or another backend is a one-line image change. → *Push back if you have a strong preference for a different local dev backend.*

5. **Local → S3 migration only.** Reverse migration (S3 → local) is not implemented. If needed, use `aws s3 sync` or equivalent. → *Push back if you anticipate needing to move back to local storage.*

6. **Bucket auto-creation at controller startup.** The controller checks for the configured bucket on startup and creates it if absent (using `create_bucket` with appropriate region config). This avoids a separate init container in compose. → *Push back if you prefer explicit bucket provisioning.*

7. **`LAYERSENSE_S3_PUBLIC_ENDPOINT_URL` host-rewrite approach for local dev.** Presigned URLs are generated against the internal compose hostname, then the host is rewritten to the public endpoint before the `RedirectResponse` is issued. This assumes the S3-compatible backend does not include the host in the signed string. → *Push back if RustFS includes the host in its signature (requires verification).*

8. **No changes to the default `docker-compose.yml`.** The S3 overlay is strictly additive. Running `just docker` continues to use `LocalFSObjectStore` with no S3 services. → *This is firm; push back only if you want S3 as the default dev stack.*

9. **`just test-e2e-s3` is opt-in and not part of CI by default.** It requires a Docker environment with RustFS image access. CI runs `just test-e2e` (local backend) only. → *Push back if you want S3 coverage in CI.*

→ Correct any of these or I proceed to implementation.
