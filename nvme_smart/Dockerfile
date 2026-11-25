FROM alpine:3.20

RUN apk add --no-cache nvme-cli jq curl

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
