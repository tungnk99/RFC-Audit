# Image SUT mỏng cho một commit wolfSSL: ảnh HEAD (chứng chỉ, tlsfuzzer, tlslite-ng) cộng máy chủ đã dựng và `.rev` của commit.
# Do scripts/eval_build_binaries.py gọi; ngữ cảnh build là runs/real/binaries/<sha12> chứa `server` và `rev`.
#   docker build -f docker/eval-binary.Dockerfile -t rfcv/sut-wolfssl:<sha12> runs/real/binaries/<sha12>
FROM rfcv/sut-wolfssl:head
COPY --chmod=0755 server /sut/examples/server/server
COPY rev /sut/.rev
