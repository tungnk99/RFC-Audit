# Image SUT SSH (Dropbear) dựng từ git, hỗ trợ phủ overlay/ cho mutant (Held-out protocol 1).
FROM debian:bookworm-slim AS build
ARG REV=DROPBEAR_2024.86
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates gcc libc6-dev make autoconf zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${REV}" --quiet https://github.com/mkj/dropbear.git /src/dropbear \
 && git -C /src/dropbear rev-parse HEAD > /src/REV
COPY overlay/ /src/dropbear/
RUN cd /src/dropbear && autoconf && autoheader \
 && ./configure --disable-pam --disable-lastlog --disable-utmp --disable-utmpx --disable-wtmp --disable-wtmpx >/dev/null \
 && make -j"$(nproc)" PROGRAMS="dropbear" >/tmp/make.log 2>&1 || (tail -40 /tmp/make.log; exit 1)

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 zlib1g \
 && rm -rf /var/lib/apt/lists/* && mkdir -p /sut
COPY --from=build /src/dropbear/dropbear /sut/dropbear
COPY --from=build /src/REV /sut/.rev
RUN chmod 755 /sut/dropbear
USER nobody
