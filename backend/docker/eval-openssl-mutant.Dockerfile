# Image SUT cho một mutant OpenSSL: dựa trên ảnh dựng sẵn (stage `build` của eval-openssl.Dockerfile), chỉ biên dịch lại các tệp bị sửa.
#   docker build --target build -f docker/eval-openssl.Dockerfile -t rfcv/sut-build-openssl:head runs/real/openssl-head
#   docker build -f docker/eval-openssl-mutant.Dockerfile --build-arg SHA=<commit mutant> -t rfcv/sut-openssl:<sha12> runs/real/mutants/<id>
FROM rfcv/sut-build-openssl:head AS build
ARG SHA
COPY overlay/ /src/openssl/
RUN cd /src/openssl && find . -newer /src/REV -name '*.c' -exec touch {} + && make -j"$(nproc)" build_programs >/tmp/make.log 2>&1 \
 && echo "${SHA}" > /src/REV

FROM rfcv/ref-openssl:latest
COPY --from=build /src/openssl/apps/openssl /sut/openssl
COPY --from=build /src/REV /sut/.rev
