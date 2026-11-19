"""
오브젝트 저장소 — 큰 tool 결과 등 덩어리 데이터를 key 로 넣고 꺼낸다.

STORAGE=local (기본) : backend/data/blobs/<key> 파일
STORAGE=s3           : 사내 S3 호환 저장소 (boto3). S3_ENDPOINT_URL 을 비우면 AWS S3

    S3_ENDPOINT_URL=https://s3.사내도메인    S3_BUCKET=coris    S3_PREFIX=coris/
    S3_REGION=        S3_ACCESS_KEY=   S3_SECRET_KEY=   (비우면 boto3 기본 자격 증명 — 환경변수 · IAM role)

보관 기간: local 은 cleanup() 이 STORAGE_TTL_DAYS 보다 오래된 tool-results/ 를 지운다.
S3 는 버킷 lifecycle 규칙(prefix tool-results/, N일 후 삭제)으로 관리한다 — 영구 데이터와 prefix 를 나눌 것.
"""
import logging
import os
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("storage")

KIND = os.getenv("STORAGE", "local").lower()
LOCAL_ROOT = Path(os.getenv("STORAGE_LOCAL_DIR") or Path(__file__).resolve().parent.parent / "data" / "blobs")
TTL_DAYS = float(os.getenv("STORAGE_TTL_DAYS", "7"))


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError(f"잘못된 key: {key}")
        return p

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)

    def get(self, key: str) -> Optional[bytes]:
        p = self._path(key)
        return p.read_bytes() if p.exists() else None

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def cleanup(self, prefix: str, max_age_s: float) -> int:
        base = self.root / prefix
        if not base.exists():
            return 0
        cutoff, n = time.time() - max_age_s, 0
        for f in base.rglob("*"):
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                n += 1
        for d in sorted((d for d in base.rglob("*") if d.is_dir()), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()
        return n


class S3Storage:
    def __init__(self):
        try:
            import boto3  # 선택 의존성 — STORAGE=s3 일 때만 필요
        except ImportError as e:
            raise RuntimeError("STORAGE=s3 에는 boto3 가 필요합니다: pip install boto3") from e
        self.bucket = os.environ["S3_BUCKET"]
        self.prefix = os.getenv("S3_PREFIX", "")
        self.client = boto3.client(
            "s3",
            endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
            region_name=os.getenv("S3_REGION") or None,
            aws_access_key_id=os.getenv("S3_ACCESS_KEY") or None,
            aws_secret_access_key=os.getenv("S3_SECRET_KEY") or None,
        )

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.client.put_object(Bucket=self.bucket, Key=self.prefix + key, Body=data, ContentType=content_type)

    def get(self, key: str) -> Optional[bytes]:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=self.prefix + key)["Body"].read()
        except self.client.exceptions.NoSuchKey:
            return None

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self.prefix + key)

    def cleanup(self, prefix: str, max_age_s: float) -> int:
        return 0  # 버킷 lifecycle 규칙에 맡긴다


_impl = None


def backend():
    global _impl
    if _impl is None:
        _impl = S3Storage() if KIND == "s3" else LocalStorage(LOCAL_ROOT)
        log.info("저장소: %s", f"s3 ({os.getenv('S3_ENDPOINT_URL') or 'AWS'} / {os.getenv('S3_BUCKET')})" if KIND == "s3" else LOCAL_ROOT)
    return _impl


def put(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    backend().put(key, data, content_type)


def get(key: str) -> Optional[bytes]:
    return backend().get(key)


def cleanup(prefix: str = "tool-results/") -> int:
    n = backend().cleanup(prefix, TTL_DAYS * 86400)
    if n:
        log.info("저장소 정리: %s 에서 %d개 파일 삭제 (보관 %s일)", prefix, n, TTL_DAYS)
    return n
