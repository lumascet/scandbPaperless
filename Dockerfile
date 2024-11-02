FROM python:3.13-slim-bullseye

RUN apt-get update && apt-get install -y --no-install-recommends\
    imagemagick\
    img2pdf \
    poppler-utils \
    sane \
    sane-utils \
    usbutils \
    scanbd \
    dbus \
    procps \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

RUN mkdir /etc/scanbd/sane.d/ && cp -r /etc/sane.d/* /etc/scanbd/sane.d/
RUN echo 'net\nfujitsu' > /etc/sane.d/dll.conf
RUN echo 'connect_timeout = 3\nlocalhost # scanbm is listening on localhost' > /etc/sane.d/net.conf

RUN echo "Setting up user/group" \
    && addgroup --gid 1000 paperless \
    && useradd --uid 1000 --gid paperless --home-dir /home/paperless paperless \
    && addgroup paperless scanner \
    && addgroup paperless root 

RUN mkdir /home/paperless /home/paperless/scan && chown paperless:paperless /home/paperless/scan

COPY scanbd/scanbd.conf /etc/scanbd/scanbd.conf
COPY requirements.txt /requirements.txt
RUN pip install -r /requirements.txt
#COPY scanbd/run.sh /run.sh
COPY scripts /etc/scanbd/scripts
COPY scanbd/config.py /config.py
COPY scanbd/homeassistantmqtt.py /homeassistantmqtt.py
COPY scanbd/run.py /run.py
HEALTHCHECK --interval=30s --timeout=30s --start-period=1s --retries=3 CMD [ "pgrep", "-x", "scanbd" ]

ENTRYPOINT [ "python3","-u", "run.py" ]