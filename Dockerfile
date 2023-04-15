FROM alpine:3
#LABEL maintainer="kontakt@maximeveit.de"

RUN apk add --no-cache python3 unison

# Set entrypoint
ADD startup.py /opt/
ENTRYPOINT ["/opt/startup.py"]
