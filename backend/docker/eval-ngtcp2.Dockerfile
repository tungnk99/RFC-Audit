# Image SUT QUIC (ngtcp2) dựng từ git + wrapper UDP gọi trực tiếp `ngtcp2_accept()` trong libngtcp2 (Held-out protocol 2).
FROM debian:bookworm-slim AS build
ARG REV=v1.11.0
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates gcc g++ libc6-dev cmake make pkg-config \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${REV}" --quiet https://github.com/ngtcp2/ngtcp2.git /src/ngtcp2 \
 && git -C /src/ngtcp2 rev-parse HEAD > /src/REV
ARG COMMIT_REV=""
RUN if [ -n "${COMMIT_REV}" ]; then printf '%s\n' "${COMMIT_REV}" > /src/REV; fi
COPY overlay/ /src/ngtcp2/
RUN cmake -S /src/ngtcp2 -B /src/build -DENABLE_LIB_ONLY=ON -DENABLE_STATIC_LIB=ON -DENABLE_SHARED_LIB=OFF -DENABLE_OPENSSL=OFF -DENABLE_GNUTLS=OFF -DBUILD_TESTING=OFF >/dev/null \
 && cmake --build /src/build -j"$(nproc)" >/tmp/make.log 2>&1 || (tail -40 /tmp/make.log; exit 1)
RUN cat <<'EOF' > /src/rfcv_ngtcp2_srv.c
#include <arpa/inet.h>
#include <netinet/in.h>
#include <ngtcp2/ngtcp2.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

int main(int argc, char **argv) {
    int port = argc > 1 ? atoi(argv[1]) : 4433;
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) return 1;
    int opt = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((uint16_t)port);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) return 2;
    uint8_t buf[65536];
    for (;;) {
        struct sockaddr_in peer;
        socklen_t plen = sizeof(peer);
        ssize_t n = recvfrom(fd, buf, sizeof(buf), 0, (struct sockaddr *)&peer, &plen);
        if (n <= 0) continue;
        ngtcp2_pkt_hd hd;
        if (ngtcp2_accept(&hd, buf, (size_t)n) == 0) {
            uint8_t resp[32];
            memset(resp, 0, sizeof(resp));
            resp[0] = 0xC0; /* QUIC v1 Long Header Initial response */
            resp[4] = 0x01;
            sendto(fd, resp, sizeof(resp), 0, (struct sockaddr *)&peer, plen);
        }
    }
    return 0;
}
EOF
RUN gcc -O2 -I/src/ngtcp2/lib/includes -I/src/build/lib/includes /src/rfcv_ngtcp2_srv.c /src/build/lib/libngtcp2.a -o /src/rfcv_ngtcp2_srv

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
 && rm -rf /var/lib/apt/lists/* && mkdir -p /sut
COPY --from=build /src/rfcv_ngtcp2_srv /sut/rfcv_ngtcp2_srv
COPY --from=build /src/REV /sut/.rev
RUN chmod 755 /sut/rfcv_ngtcp2_srv && chmod 644 /sut/.rev
USER nobody
