# Image SUT DNS (dnsmasq) dựng từ git, hỗ trợ phủ overlay/ cho mutant.
FROM debian:bookworm-slim AS build
ARG REV=v2.90
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates gcc libc6-dev make \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${REV}" --quiet git://thekelleys.org.uk/dnsmasq.git /src/dnsmasq \
    || git clone --depth 1 --branch "${REV}" --quiet https://github.com/imp/dnsmasq.git /src/dnsmasq
RUN git -C /src/dnsmasq rev-parse HEAD > /src/REV
COPY overlay/ /src/dnsmasq/
RUN make -C /src/dnsmasq -j"$(nproc)" >/tmp/make.log 2>&1 || (tail -40 /tmp/make.log; exit 1)

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
 && rm -rf /var/lib/apt/lists/* && mkdir -p /sut
COPY --from=build /src/dnsmasq/src/dnsmasq /sut/dnsmasq
COPY --from=build /src/REV /sut/.rev
RUN chmod 755 /sut/dnsmasq
USER nobody
