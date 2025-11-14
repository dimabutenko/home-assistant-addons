FROM crocodilestick/calibre-web-automated:latest

# Копируем наш "хак" в папку автозапуска
COPY 01-ha-links.sh /etc/cont-init.d/01-ha-links
RUN chmod a+x /etc/cont-init.d/01-ha-links