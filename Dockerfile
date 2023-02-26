FROM ubuntu:22.04

RUN apt-get update && apt-get upgrade -y && apt-get clean
RUN apt-get install software-properties-common -y
RUN add-apt-repository ppa:deadsnakes/ppa -y
RUN apt-get install -y curl git python3.7 python3.7-dev python3.7-distutils locales
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.7 1
RUN update-alternatives --set python /usr/bin/python3.7
RUN curl -s https://bootstrap.pypa.io/get-pip.py -o get-pip.py && python get-pip.py --force-reinstall && rm get-pip.py

RUN pip install supervisor && pip install "setuptools<58.0.0"
RUN cd /root && git clone https://github.com/hadalin/tocha.git && cd tocha && pip install -r requirements.txt

RUN mkdir -p /var/log/supervisor
COPY ./conf/supervisor/tocha.conf /etc/supervisor/supervisord.conf
COPY ./all.conf /root/tocha
COPY ./ljubljana.conf /root/tocha

RUN echo "sl_SI.UTF-8 UTF-8" > /etc/locale.gen
RUN locale-gen
ENV LC_ALL=sl_SI.UTF-8
ENV LC_CTYPE=sl_SI.UTF-8

ADD entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]