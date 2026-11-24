# Image SUT DNS (Knot DNS v3.4.2) dựng từ git, hỗ trợ phủ overlay/ cho mutant.
FROM debian:bookworm-slim AS build
ARG REV=v3.4.2
ARG COMMIT_REV=""
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates gcc libc6-dev make autoconf automake libtool pkg-config \
    liburcu-dev libgnutls28-dev liblmdb-dev libedit-dev libnghttp2-dev \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${REV}" --quiet https://github.com/CZ-NIC/knot /src/knot \
 && git -C /src/knot rev-parse HEAD > /src/REV
COPY overlay/ /src/knot/
RUN if [ -n "${COMMIT_REV}" ]; then printf '%s\n' "${COMMIT_REV}" > /src/REV; fi \
 && cd /src/knot && autoreconf -if >/dev/null 2>&1 \
 && ./configure --disable-documentation --disable-fastparser --disable-dnstap --disable-quic --disable-xdp --disable-utilities >/dev/null \
 && make -j"$(nproc)" >/tmp/make.log 2>&1 || (tail -40 /tmp/make.log; exit 1) \
 && make install >/dev/null 2>&1

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 liburcu8 libgnutls30 liblmdb0 libedit2 \
 && rm -rf /var/lib/apt/lists/* && mkdir -p /sut /tmp/knot-storage /tmp/knot-run
COPY --from=build /usr/local/sbin/knotd /sut/knotd
COPY --from=build /usr/local/lib/libknot* /usr/local/lib/libdnssec* /usr/local/lib/libzscanner* /usr/lib/
COPY --from=build /src/REV /sut/.rev
RUN printf 'server:\n  listen: 127.0.0.1@5353\n  rundir: /tmp\n  user: nobody:nogroup\ndatabase:\n  storage: /tmp\nzone:\n  - domain: example.test\n    file: /sut/example.test.zone\n' > /sut/knot.conf \
 && printf '$ORIGIN example.test.\n@ 3600 IN SOA ns1.example.test. hostmaster.example.test. 1 3600 600 86400 300\n@ 3600 IN NS ns1.example.test.\n@ 3600 IN A 127.0.0.1\nns1 3600 IN A 127.0.0.1\n' > /sut/example.test.zone \
 && ldconfig && chmod 755 /sut/knotd
USER nobody
