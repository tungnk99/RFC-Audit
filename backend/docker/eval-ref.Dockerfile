# Hai bản tham chiếu ĐỘC LẬP làm nhân chứng dương cho Test driver (thiết kế đánh giá; adapter `references`):
#   docker build -f docker/eval-ref.Dockerfile --target openssl -t rfcv/ref-openssl:latest .
#   docker build -f docker/eval-ref.Dockerfile --target gnutls  -t rfcv/ref-gnutls:latest  .
# Thiết kế gốc dùng rustls + OpenSSL; vòng này dùng OpenSSL + GnuTLS (gói Debian, dựng trong vài phút). Ghi rõ trong báo cáo.
# Cùng bố cục với eval-sut.Dockerfile (/opt/tlslite-ng, /opt/tlsfuzzer, /opt/venv) để dùng chung runner kiểm thử.
# Chứng chỉ tự ký, khoá dùng một lần cho thử nghiệm (không bí mật); container chạy không mạng.
FROM debian:bookworm-slim AS tools

ARG TLSFUZZER_REV=5eebc4464e5197a7f7392fb9acda99cfc32441f7
ARG TLSLITE_REV=7e95ea1a86c0d42d8d931ff14134d31f01ce1d76

RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates python3 python3-pip python3-venv openssl \
 && rm -rf /var/lib/apt/lists/*

RUN git clone --quiet https://github.com/tlsfuzzer/tlsfuzzer /opt/tlsfuzzer && git -C /opt/tlsfuzzer checkout --quiet "${TLSFUZZER_REV}" \
 && git clone --quiet https://github.com/tlsfuzzer/tlslite-ng /opt/tlslite-ng && git -C /opt/tlslite-ng checkout --quiet "${TLSLITE_REV}" \
 && python3 -m venv /opt/venv && /opt/venv/bin/pip install --quiet ecdsa six

# RSA vì ClientHello của tlsfuzzer chào rsa_pss_rsae_sha256.
RUN mkdir /ref \
 && openssl req -x509 -newkey rsa:2048 -nodes -keyout /ref/key.pem -out /ref/cert.pem -days 3650 -subj "/CN=localhost" 2>/dev/null \
 && chmod 644 /ref/key.pem /ref/cert.pem

FROM debian:bookworm-slim AS base
RUN apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/* \
 && useradd -u 65532 -m runner
COPY --from=tools /opt /opt
COPY --from=tools /ref /ref
ENV PYTHONPATH=/opt/tlslite-ng:/opt/tlsfuzzer
WORKDIR /ref

# Khởi chạy server theo launcher (docker/docker_launcher.py):
#   openssl s_server -accept 4433 -cert /ref/cert.pem -key /ref/key.pem -tls1_3 -www
FROM base AS openssl
RUN apt-get update && apt-get install -y --no-install-recommends openssl && rm -rf /var/lib/apt/lists/*
USER 65532:65532

#   gnutls-serv --port 4433 --x509certfile /ref/cert.pem --x509keyfile /ref/key.pem --priority NORMAL:-VERS-ALL:+VERS-TLS1.3 --disable-client-cert --http
FROM base AS gnutls
RUN apt-get update && apt-get install -y --no-install-recommends gnutls-bin && rm -rf /var/lib/apt/lists/*
USER 65532:65532
