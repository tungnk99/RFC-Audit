# Image SUT cho một mutant: dựa trên ảnh HEAD đã dựng, chỉ biên dịch lại tệp bị sửa và thay tệp chạy server (lớp rất nhỏ).
# Điều kiện: đã có rfcv/sut-build:head (docker build --target build -f docker/eval-sut.Dockerfile --build-arg WOLFSSL_REV=28bc7540d
#   -t rfcv/sut-build:head .) và rfcv/sut-wolfssl:head.
#   docker build -f docker/eval-mutant.Dockerfile --build-arg SHA=<commit mutant> -t rfcv/sut-wolfssl:<sha12> runs/real/mutants/<id>
# Ngữ cảnh build là thư mục của mutant, chỉ chứa internal.c đã sửa. Do scripts/eval_make_mutants.py --images gọi.
FROM rfcv/sut-build:head AS build
ARG SHA
COPY internal.c /src/wolfssl/src/internal.c
RUN cd /src/wolfssl && touch src/internal.c && make -j"$(nproc)" examples/server/server >/dev/null \
 && echo "${SHA}" > /src/REV

FROM rfcv/sut-wolfssl:head
COPY --from=build /src/wolfssl/examples/server/server /sut/examples/server/server
COPY --from=build /src/REV /sut/.rev
