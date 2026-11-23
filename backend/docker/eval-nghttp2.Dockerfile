# Image SUT HTTP/2 (nghttp2 / nghttpd --no-tls) dựng từ git, hỗ trợ phủ overlay/ cho mutant.
FROM debian:bookworm-slim AS build
ARG REV=v1.64.0
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates gcc g++ libc6-dev make autoconf automake libtool pkg-config \
    libssl-dev libev-dev zlib1g-dev libnghttp2-dev \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${REV}" --quiet https://github.com/nghttp2/nghttp2 /src/nghttp2 \
 && git -C /src/nghttp2 rev-parse HEAD > /src/REV
COPY overlay/ /src/nghttp2/
RUN cd /src/nghttp2 && autoreconf -i >/dev/null 2>&1 \
 && ./configure --enable-app --disable-examples --disable-hpack-tools --disable-python-bindings --disable-threads >/dev/null \
 && make -j"$(nproc)" >/tmp/make.log 2>&1 || (tail -40 /tmp/make.log; exit 1)

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 libev4 libssl3 zlib1g \
 && rm -rf /var/lib/apt/lists/* && mkdir -p /sut
COPY --from=build /src/nghttp2/src/nghttpd /sut/nghttpd
COPY --from=build /src/nghttp2/lib/.libs/libnghttp2.so* /usr/lib/
COPY --from=build /src/REV /sut/.rev
RUN ldconfig && chmod 755 /sut/nghttpd
USER nobody
