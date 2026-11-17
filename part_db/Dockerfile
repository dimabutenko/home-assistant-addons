FROM jbtronics/part-db1:2.20.7

COPY ha-ingress.conf /etc/apache2/conf-available/ha-ingress.conf
COPY ha-entrypoint.sh /usr/local/bin/ha-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/ha-entrypoint.sh /etc/apache2/conf-available/ha-ingress.conf \
    && chmod 0755 /usr/local/bin/ha-entrypoint.sh \
    && a2enconf ha-ingress

# Defaults for a single-user Home Assistant add-on. APP_SECRET is generated on first start.
ENV DEFAULT_LANG=ru \
    DEFAULT_TIMEZONE=Europe/Warsaw \
    INSTANCE_NAME=Part-DB \
    DB_AUTOMIGRATE=true \
    DATABASE_SQLITE_ENFORCE_FOREIGN_KEYS=1 \
    MCP_ENABLED=1 \
    TRUSTED_PROXIES=127.0.0.0/8,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16

# A new ENTRYPOINT resets CMD, so repeat the upstream one.
ENTRYPOINT ["ha-entrypoint.sh"]
CMD ["/usr/local/bin/apache2-foreground"]
