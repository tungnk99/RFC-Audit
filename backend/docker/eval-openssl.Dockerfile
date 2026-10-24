# Image SUT OpenSSL dựng từ git (openssl/openssl) tại một thẻ cố định, tuỳ chọn phủ lên các tệp nguồn đã sửa (mutant).
# Ngữ cảnh build: thư mục chứa `overlay/` (có thể rỗng; tệp trong đó đè lên cây nguồn theo đường dẫn tương đối).
#   docker build -f docker/eval-openssl.Dockerfile --build-arg REV=openssl-3.6.5 -t rfcv/sut-openssl:head <ngữ cảnh>
# Chạy: /sut/openssl s_server -accept 4433 -cert /ref/cert.pem -key /ref/key.pem -tls1_3 -www (xem docker_launcher.py).
FROM debian:bookworm-slim AS build
ARG REV=openssl-3.6.5
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates gcc libc6-dev make perl \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --quiet https://github.com/openssl/openssl /src/openssl \
 && git -C /src/openssl checkout --quiet "${REV}" && git -C /src/openssl rev-parse HEAD > /src/REV
COPY overlay/ /src/openssl/
RUN cd /src/openssl && ./Configure no-shared no-tests no-docs no-afalgeng >/dev/null \
 && make -j"$(nproc)" build_programs >/tmp/make.log 2>&1 || (tail -30 /tmp/make.log; exit 1)

FROM rfcv/ref-openssl:latest
COPY --from=build /src/openssl/apps/openssl /sut/openssl
COPY --from=build /src/REV /sut/.rev
