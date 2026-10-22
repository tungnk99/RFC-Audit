# Sandbox ANALYSIS ZONE cho công cụ đọc mã (tài liệu khám phá mã, mục 5, Bảng 6). Hai image, dựng từ gốc repo:
#
#   docker build -f docker/code-index-worker.Dockerfile --target indexer -t rfcv/code-indexer:latest .
#   docker build -f docker/code-index-worker.Dockerfile --target worker  -t rfcv/code-index-worker:latest .
#
# - indexer: dựng chỉ mục SQLite bằng tree-sitter, chạy một lần mỗi lần chạy (rfcv.codeindex.providers.indexer_args):
#     --network none --read-only, kho mã gắn chỉ đọc ở /repo, chỉ /out ghi được, user 65532.
# - worker: chạy lệnh của explore/search_text bằng `docker exec … timeout -s KILL 10 <argv>` (rfcv.codeindex.executors):
#     --network none --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges --pids-limit 64
#     --memory 512m --cpus 1 --user 65532:65532, kho mã gắn chỉ đọc ở /repo.
#   Image worker chỉ có các lệnh ở Bảng 3 (cùng sleep, timeout của coreutils mà harness dùng): không shell, không
#   trình thông dịch, không trình biên dịch.
# Digest hai image được ghi vào bản kê lần chạy (image:code-indexer, image:code-index-worker).

ARG RIPGREP_VERSION=14.1.1
ARG AST_GREP_VERSION=0.38.6

# ---------------------------------------------------------------- tải công cụ (không vào image cuối)
FROM debian:bookworm-slim AS tools
ARG RIPGREP_VERSION
ARG AST_GREP_VERSION
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl unzip \
 && curl -fsSL -o /tmp/rg.tgz \
      "https://github.com/BurntSushi/ripgrep/releases/download/${RIPGREP_VERSION}/ripgrep-${RIPGREP_VERSION}-x86_64-unknown-linux-musl.tar.gz" \
 && tar -xzf /tmp/rg.tgz -C /tmp \
 && install -m 0755 "/tmp/ripgrep-${RIPGREP_VERSION}-x86_64-unknown-linux-musl/rg" /usr/local/bin/rg \
 && curl -fsSL -o /tmp/sg.zip \
      "https://github.com/ast-grep/ast-grep/releases/download/${AST_GREP_VERSION}/app-x86_64-unknown-linux-gnu.zip" \
 && unzip /tmp/sg.zip -d /tmp/sg \
 && install -m 0755 /tmp/sg/ast-grep /usr/local/bin/sg

# ---------------------------------------------------------------- indexer
FROM python:3.12-slim AS indexer
RUN pip install --no-cache-dir "tree-sitter>=0.23,<0.26" "tree-sitter-c>=0.23,<0.25" "tree-sitter-rust>=0.23,<0.25" \
      "tree-sitter-go>=0.23,<0.26"
COPY src/rfcv/__init__.py /opt/rfcv/rfcv/__init__.py
COPY src/rfcv/codeindex/__init__.py src/rfcv/codeindex/__main__.py src/rfcv/codeindex/builder.py \
     src/rfcv/codeindex/languages.py /opt/rfcv/rfcv/codeindex/
ENV PYTHONPATH=/opt/rfcv PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
WORKDIR /repo

# ---------------------------------------------------------------- worker
FROM debian:bookworm-slim AS worker
COPY --from=tools /usr/local/bin/rg /usr/local/bin/sg /usr/local/bin/
# Giữ: coreutils (ls, cat, head, tail, wc, sort, uniq, cut, sleep, timeout), findutils (find), sed, grep, tree.
# Gỡ mọi shell và trình thông dịch có sẵn trong debian-slim; agent vốn không gọi được chúng (danh sách cho phép),
# đây là lớp phòng thủ thứ hai.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tree \
 && rm -rf /var/lib/apt/lists/* \
 && rm -f /usr/bin/perl* /usr/bin/mawk /usr/bin/awk /etc/alternatives/awk /usr/bin/xargs /usr/bin/env \
          /usr/bin/python* /usr/bin/dpkg* /usr/bin/apt* \
 && rm -f /bin/bash /usr/bin/bash /bin/rbash /usr/bin/rbash /bin/dash /usr/bin/dash /bin/sh /usr/bin/sh
USER 65532:65532
WORKDIR /repo
# Không ENTRYPOINT shell: container chạy `sleep infinity`, lệnh do Code gate truyền dạng argv qua docker exec.
ENTRYPOINT ["/usr/bin/sleep"]
CMD ["infinity"]
