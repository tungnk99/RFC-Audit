# Image dựng SUT wolfSSL cho một commit + tlsfuzzer cố định (thiết kế đánh giá mục 9 bước 1; adapter tls13/sut/wolfssl.yaml).
# Mỗi (commit, cờ build) một image; ghi digest vào bản kê lần chạy.
#   docker build -f docker/eval-sut.Dockerfile \
#     --build-arg WOLFSSL_REV=c18833f52^ --build-arg TAG=bug -t rfcv/sut-wolfssl:bug .
# Dựng từ thư mục gốc repo; mã wolfSSL lấy từ eval/work/wolfssl (đã clone bằng scripts/eval_prepare.ps1).
FROM debian:bookworm-slim AS build

ARG WOLFSSL_REV
ARG TLSFUZZER_REV=5eebc4464e5197a7f7392fb9acda99cfc32441f7
ARG TLSLITE_REV=7e95ea1a86c0d42d8d931ff14134d31f01ce1d76
ARG CFLAGS_EXTRA="-DWOLFSSL_TLS13_MIDDLEBOX_COMPAT"
ARG CONFIGURE_FLAGS="--enable-tls13 --disable-shared --enable-static"

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential autoconf automake libtool pkg-config git ca-certificates python3 python3-pip python3-venv \
 && rm -rf /var/lib/apt/lists/*

COPY eval/work/wolfssl /src/wolfssl
WORKDIR /src/wolfssl
RUN git checkout --quiet "${WOLFSSL_REV}" \
 && ./autogen.sh \
 && ./configure ${CONFIGURE_FLAGS} CFLAGS="${CFLAGS_EXTRA}" \
 && make -j"$(nproc)" examples/server/server \
 && git rev-parse HEAD > /src/REV

# Bộ công cụ kiểm thử lấy từ mã nguồn ở commit cố định, không dùng PyPI.
RUN git clone --quiet https://github.com/tlsfuzzer/tlsfuzzer /opt/tlsfuzzer && git -C /opt/tlsfuzzer checkout --quiet "${TLSFUZZER_REV}" \
 && git clone --quiet https://github.com/tlsfuzzer/tlslite-ng /opt/tlslite-ng && git -C /opt/tlslite-ng checkout --quiet "${TLSLITE_REV}" \
 && python3 -m venv /opt/venv && /opt/venv/bin/pip install --quiet ecdsa six

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/* \
 && useradd -u 65532 -m runner
COPY --from=build /src/wolfssl /sut
COPY --from=build /src/REV /sut/.rev
COPY --from=build /opt /opt
ENV PYTHONPATH=/opt/tlslite-ng:/opt/tlsfuzzer
USER 65532:65532
WORKDIR /sut
# Không ENTRYPOINT shell: Test driver truyền argv. Khởi chạy SUT theo adapter:
#   ./examples/server/server -v 4 -d -g -i -p 4433
