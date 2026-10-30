FROM alpine:3.21

COPY entrypoint.sh /usr/local/bin/natapp-entrypoint
RUN chmod +x /usr/local/bin/natapp-entrypoint

ENTRYPOINT ["/usr/local/bin/natapp-entrypoint"]
