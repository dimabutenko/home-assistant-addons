FROM alpine:latest

# Устанавливаем Samba
RUN apk add --no-cache samba

# Копируем наш готовый конфигурационный файл в контейнер
COPY smb.conf /etc/samba/smb.conf

# Открываем стандартные порты Samba наружу
EXPOSE 139 445

# Запускаем Samba в фоновом режиме (демон smbd), не закрывая контейнер
CMD ["smbd", "--foreground", "--no-process-group"]
