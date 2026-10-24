# Image SUT mbedTLS dựng từ git (Mbed-TLS/mbedtls) tại một thẻ/commit cố định, tuỳ chọn phủ lên các tệp thư viện đã sửa (mutant).
# Ngữ cảnh build: thư mục chứa `overlay/` (có thể rỗng; tệp trong đó đè lên cây nguồn theo đường dẫn tương đối).
#   docker build -f docker/eval-mbedtls.Dockerfile --build-arg REV=mbedtls-3.6.7 -t rfcv/sut-mbedtls:head <ngữ cảnh>
# Chạy: /sut/ssl_server2 server_port=4433 force_version=tls13 crt_file=/ref/cert.pem key_file=/ref/key.pem (xem docker_launcher.py).
FROM debian:bookworm-slim AS build
ARG REV=mbedtls-3.6.7
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates gcc libc6-dev make cmake perl python3 python3-venv \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --quiet https://github.com/Mbed-TLS/mbedtls /src/mbedtls \
 && git -C /src/mbedtls checkout --quiet "${REV}" && git -C /src/mbedtls submodule update --init --recursive --quiet \
 && git -C /src/mbedtls rev-parse HEAD > /src/REV
COPY overlay/ /src/mbedtls/
RUN cd /src/mbedtls && cmake -S . -B build -DENABLE_TESTING=Off -DENABLE_PROGRAMS=On -DMBEDTLS_FATAL_WARNINGS=Off >/dev/null \
 && cmake --build build --target ssl_server2 -j"$(nproc)" >/tmp/make.log 2>&1 || (tail -30 /tmp/make.log; exit 1)

FROM rfcv/ref-openssl:latest
COPY --from=build /src/mbedtls/build/programs/ssl/ssl_server2 /sut/ssl_server2
COPY --from=build /src/REV /sut/.rev
