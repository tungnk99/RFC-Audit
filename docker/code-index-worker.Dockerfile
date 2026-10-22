# Sandbox ANALYSIS ZONE cho công cụ đọc mã (tài liệu khám phá mã, mục 5, Bảng 6).
# Chỉ có các lệnh đọc trong danh sách cho phép; không trình biên dịch, không shell cho agent.
# Chạy với:
#   docker run --rm --network none --read-only --tmpfs /tmp:size=256m \
#     --cap-drop ALL --security-opt no-new-privileges --pids-limit 128 \
#     --memory 1g --cpus 1 --user 65532:65532 \
#     -v <repo@commit>:/repo:ro rfcv/code-index-worker:<digest>
# Ghi digest image vào bản kê lần chạy.
FROM debian:bookworm-slim

ARG RIPGREP_VERSION=14.1.1
ARG AST_GREP_VERSION=0.38.6

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl tree \
 && curl -fsSL -o /tmp/rg.deb \
      "https://github.com/BurntSushi/ripgrep/releases/download/${RIPGREP_VERSION}/ripgrep_${RIPGREP_VERSION}-1_amd64.deb" \
 && dpkg -i /tmp/rg.deb \
 && curl -fsSL -o /tmp/sg.zip \
      "https://github.com/ast-grep/ast-grep/releases/download/${AST_GREP_VERSION}/app-x86_64-unknown-linux-gnu.zip" \
 && apt-get install -y --no-install-recommends unzip && unzip /tmp/sg.zip -d /usr/local/bin \
 && apt-get purge -y curl unzip && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* /tmp/*

USER 65532:65532
WORKDIR /repo
# Không có ENTRYPOINT shell: lệnh do Code gate truyền dạng argv (execve).
